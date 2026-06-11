#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
#  test_engine.py — Test engine HEADLESS (không gọi mạng) bằng MockProvider.
#  Chạy:  python3 tests/test_engine.py
# ============================================================================
import os, sys, json, threading, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E

PASS = 0; FAIL = 0
def check(name, cond, extra=''):
    global PASS, FAIL
    if cond: PASS += 1; print('  ✓ %s' % name)
    else:    FAIL += 1; print('  ✗ %s  %s' % (name, extra))

# ---------------------------------------------------------------------------
# MockProvider: trả JSON array dịch giả, giữ nguyên dòng có placeholder.
# Có thể mô phỏng 502 (Transient) N lần đầu rồi mới OK.
# ---------------------------------------------------------------------------
class MockProvider(E.Provider):
    name = 'mock'
    def __init__(self, fail_first=0, **kw):
        super().__init__('http://mock', **kw)
        self.fail_first = fail_first
        self.calls = 0; self.lock = threading.Lock()
    def call(self, model, key, system, user):
        with self.lock:
            self.calls += 1; n = self.calls
        if n <= self.fail_first:
            raise E.Transient('HTTP 502')
        # build_user_prompt nối payload JSON sau "\n\n" cuối cùng (rfind('[') sai khi item có
        # mảng placeholders ["{0}"] -> dấu [ cuối nằm trong placeholders, không phải mở payload).
        payload = json.loads(user.rsplit('\n\n', 1)[-1])
        out = [{'id': it['id'],
                'vi': (it['en'] if ('{' in it['en'] or '<' in it['en']) else 'VI_' + it['en'])}
               for it in payload]
        return json.dumps(out, ensure_ascii=False)

def run_with_provider(cfg, provider):
    """Chạy TranslationRun nhưng thay provider bằng mock."""
    evts = []
    stop = threading.Event()
    run = E.TranslationRun(cfg, evts.append, stop)
    run.provider = provider
    run.run()
    return evts

# ---------------------------------------------------------------------------
print('\n[1] Hàm thuần')
check('parse_json_array fences', E.parse_json_array('```json\n[{"id":0,"vi":"A"}]\n```') == [{'id':0,'vi':'A'}])
check('parse_json_array text thừa', E.parse_json_array('Đây:[{"id":1,"vi":"B"}] hết') == [{'id':1,'vi':'B'}])
check('extract_placeholders', E.extract_placeholders('Press {0} <b>x</b>\\n %s') == ['{0}','<b>','</b>','\\n','%s'])
check('check_line ok', E.check_line('Hi {0}', 'Chào {0}') == [])
check('check_line lệch biến', 'lệch_{biến}' in E.check_line('Hi {0}', 'Chào bạn'))
check('check_line rỗng', E.check_line('Hi', '') == ['rỗng'])
b = E.make_batches([{'en':'x'*100,'id':i} for i in range(10)], 3, 999999)
check('make_batches maxlines', [len(x) for x in b] == [3,3,3,1], str([len(x) for x in b]))
up = E.build_user_prompt([{'id':0,'en':'Start','placeholders':[]}])
check('build_user_prompt nhúng JSON', '[{"id": 0' in up)
s = E.sample_for_prompt([('K%d'%i,'line %d here'%i) for i in range(500)], max_lines=20)
check('sample_for_prompt rải đều', len(s.split('\n')) == 20)

# ---------------------------------------------------------------------------
print('\n[2] Provider builders (không gọi mạng)')
op = E.OpenAIProvider('https://x.y/v1')
check('OpenAI endpoint', op.endpoint() == 'https://x.y/v1/chat/completions')
check('OpenAI header Bearer', op.headers('K') == {'Authorization': 'Bearer K'})
ob = op.build_body('m', 'SYS', 'USR')
check('OpenAI body messages', ob['messages'][0]['role']=='system' and ob['messages'][1]['content']=='USR')
check('OpenAI body max_tokens', 'max_tokens' in ob)
check('OpenAI parse_content', op.parse_content({'choices':[{'message':{'content':'hi'}}]}) == 'hi')
check('OpenAI parse_models', op.parse_models({'data':[{'id':'b'},{'id':'a'}]}) == ['a','b'])

# normalize base_url: chỉ cần domain, tự thêm /v1, bỏ '/' thừa, nâng http->https (host công khai)
check('OpenAI domain -> /v1 + https', E.OpenAIProvider('http://chat.trollllm.xyz').endpoint() == 'https://chat.trollllm.xyz/v1/chat/completions')
check('OpenAI domain dư /', E.OpenAIProvider('https://x.y///').endpoint() == 'https://x.y/v1/chat/completions')
check('OpenAI sẵn /v1/', E.OpenAIProvider('https://x.y/v1/').endpoint() == 'https://x.y/v1/chat/completions')
check('OpenAI models domain', E.OpenAIProvider('https://x.y').list_models_endpoint() == 'https://x.y/v1/models')
check('localhost giữ http', E.OpenAIProvider('http://localhost:8080').endpoint() == 'http://localhost:8080/v1/chat/completions')
check('LAN giữ http', E.OpenAIProvider('http://192.168.1.5:1234').endpoint() == 'http://192.168.1.5:1234/v1/chat/completions')

ap = E.AnthropicProvider('https://api.anthropic.com')
check('Anthropic endpoint (+/v1/messages)', ap.endpoint() == 'https://api.anthropic.com/v1/messages')
check('Anthropic endpoint base có /v1', E.AnthropicProvider('https://x/v1').endpoint() == 'https://x/v1/messages')
check('Anthropic domain dư /', E.AnthropicProvider('https://x//').endpoint() == 'https://x/v1/messages')
check('Anthropic header x-api-key', ap.headers('K') == {'x-api-key':'K','anthropic-version':'2023-06-01'})
ab = ap.build_body('m','SYS','USR')
check('Anthropic body system field', ab['system']=='SYS' and ab['messages'][0]['role']=='user')
check('Anthropic parse_content', ap.parse_content({'content':[{'type':'text','text':'hi'}]}) == 'hi')
check('Anthropic list_models none', ap.list_models_endpoint() is None)

# ---------------------------------------------------------------------------
print('\n[3] Map lỗi HTTP (theo status_code)')
class _R:   # giả lập httpx.Response
    def __init__(self, code, text=''): self.status_code=code; self.text=text
def maps_to(code, exc, text=''):
    try: E.Provider('http://x')._raise_for_status(_R(code, text))
    except exc: return True
    except Exception: return False
    return False
def no_raise(code):
    try: E.Provider('http://x')._raise_for_status(_R(code)); return True
    except Exception: return False
check('200 không raise', no_raise(200))
check('429 -> RateLimit', maps_to(429, E.RateLimit))
check('401 -> DeadKey', maps_to(401, E.DeadKey))
check('502 -> Transient', maps_to(502, E.Transient))
check('400 -> Transient', maps_to(400, E.Transient, 'bad'))

# ---------------------------------------------------------------------------
print('\n[4] run_translation end-to-end (MockProvider)')
work = tempfile.mkdtemp(prefix='dich_test_')
try:
    src = os.path.join(work, 'in.txt'); out = os.path.join(work, 'in_VI.txt')
    lines = ['# comment giữ nguyên', 'MENU_START=Start Game', 'HINT=Press {0} to go',
             'SAME=SAME', 'EMPTY='] + ['L%d=Line number %d here now'%(i,i) for i in range(40)]
    open(src,'w',encoding='utf-8').write('\n'.join(lines)+'\n')
    cfg = dict(src=src, out=out, keys=['k1'], model='m', models=['m'],
               workers=6, maxlines=8, maxchars=8000, retries=3, rounds=4,
               max_tokens=8192, temperature=0.3, timeout=30, sysprompt='TEST PROMPT')
    evts = run_with_provider(cfg, MockProvider())
    res = open(out, encoding='utf-8').read()
    fin = [e for e in evts if e['type']=='finished']
    check('finished ok', fin and fin[-1]['status']=='ok', str(fin[-1] if fin else None))
    check('comment giữ nguyên', '# comment giữ nguyên' in res)
    check('dịch có VI_', 'MENU_START=VI_Start Game' in res)
    check('placeholder giữ', 'HINT=Press {0} to go' in res)
    check('dòng SAME giữ', 'SAME=SAME' in res)
    done_n = len([x for x in open(out+'.done.txt') if x.strip()])
    check('.done.txt đủ key (>=41)', done_n >= 41, 'done=%d'%done_n)
    check('có event batch_init', any(e['type']=='batch_init' for e in evts))
    check('có event progress', any(e['type']=='progress' for e in evts))
    check('có event worker', any(e['type']=='worker' for e in evts))

    # --- mô phỏng 502: 5 lần đầu Transient rồi OK -> vẫn dịch xong ---
    out2 = os.path.join(work, 'in2_VI.txt')
    cfg2 = dict(cfg); cfg2['out']=out2
    evts2 = run_with_provider(cfg2, MockProvider(fail_first=5))
    fin2 = [e for e in evts2 if e['type']=='finished']
    check('502 retry rồi xong', fin2 and fin2[-1]['status']=='ok', str(fin2[-1] if fin2 else None))
    check('có event batch retry', any(e['type']=='batch' and e.get('state')=='retry' for e in evts2))

    # --- resume: chạy lại trên out đã dịch xong -> không cần dịch thêm ---
    evts3 = run_with_provider(dict(cfg), MockProvider())
    fin3 = [e for e in evts3 if e['type']=='finished']
    check('resume nhận file đã dịch', fin3 and fin3[-1]['status']=='ok')
finally:
    shutil.rmtree(work, ignore_errors=True)

# ---------------------------------------------------------------------------
print('\n[5] pick_combo cooldown')
cfg = dict(keys=['k1'], models=['m1','m2'], src='', out='')
run = E.TranslationRun(cfg, lambda e: None, threading.Event())
import time as _t
with run.lock: run.combo_ok[('m1','k1')] = _t.time() + 999  # m1 đang cooldown
mdl, key = run.pick_combo()
check('pick_combo né combo cooldown', (mdl,key) == ('m2','k1'), '%s,%s'%(mdl,key))
run2 = E.TranslationRun(dict(keys=[], models=['m'], src='', out=''), lambda e: None, threading.Event())
check('pick_combo không key -> NOKEY', run2.pick_combo()[0] == '__NOKEY__')
# chỉ 1 model (auto-switch tắt) + combo cooldown -> CHỜ, KHÔNG nhảy model khác
run3 = E.TranslationRun(dict(keys=['k1'], models=['only'], src='', out=''), lambda e: None, threading.Event())
with run3.lock: run3.combo_ok[('only','k1')] = _t.time() + 999
check('1 model cooldown -> WAIT (không đổi model)', run3.pick_combo()[0] == '__WAIT__')

# ---------------------------------------------------------------------------
print('\n[6] Checkpoint / Resume (ghi nhớ mốc đã dịch)')
work = tempfile.mkdtemp(prefix='dich_resume_')
try:
    src = os.path.join(work, 'in.txt'); out = os.path.join(work, 'in_VI.txt')
    lines = ['MENU=Start', 'HINT=Press {0}', 'SAME=SAME', 'EMPTY='] + ['L%d=Line %d'%(i,i) for i in range(20)]
    open(src,'w',encoding='utf-8').write('\n'.join(lines)+'\n')
    cfg = dict(src=src, out=out, keys=['k'], model='m', models=['m'], workers=4,
               maxlines=5, maxchars=8000, retries=2, rounds=3, max_tokens=8192,
               temperature=0.3, timeout=30, sysprompt='T')

    st0 = E.resume_status(src, out)
    check('resume_status ban đầu done=0', st0['done']==0 and st0['todo']==st0['total'], str(st0))

    # dịch ĐỢT 1 nhưng DỪNG sớm (stop sau ~vài lô) -> mô phỏng tắt tool giữa chừng
    stop = threading.Event()
    mp = MockProvider()
    calls = {'n': 0}
    orig = mp.call
    def slow_call(*a, **k):
        calls['n'] += 1
        if calls['n'] >= 2: stop.set()      # dừng sau 1-2 lô
        return orig(*a, **k)
    mp.call = slow_call
    r = E.TranslationRun(cfg, lambda e: None, stop); r.provider = mp; r.run()
    st1 = E.resume_status(src, out)
    check('sau khi dừng: đã lưu 1 phần (0<done<total)', 0 < st1['done'] < st1['total'], str(st1))
    partial = st1['done']

    # KHỞI ĐỘNG LẠI (provider mới) -> chỉ dịch phần CÒN LẠI, không từ đầu
    seen_todo = {'n': None}
    def cap(e):
        if e.get('type')=='log' and 'BẮT ĐẦU' in e.get('msg',''):
            seen_todo['n'] = e['msg']
    r2 = E.TranslationRun(cfg, cap, threading.Event()); r2.provider = MockProvider(); r2.run()
    check('resume: log báo đã xong phần trước', seen_todo['n'] and ('đã xong %d'%partial) in seen_todo['n'], str(seen_todo['n']))
    st2 = E.resume_status(src, out)
    check('resume: dịch xong hết (done==total)', st2['done']==st2['total'] and st2['total']>0, str(st2))

    # ĐỘ BỀN: xóa file output (còn done.txt) -> phải coi như chưa dịch (done=0)
    os.remove(out)
    st3 = E.resume_status(src, out)
    check('xóa output -> done.txt không gây bỏ sót (done=0)', st3['done']==0, str(st3))
finally:
    shutil.rmtree(work, ignore_errors=True)

# ---------------------------------------------------------------------------
print('\n[7] Format Resident ($KEY-block, FF7 Rebirth) — đa-format I/O')
RES = (
    'US\n'
    '$Item_E_ACC_0001\n'
    'Power Wristguards\n'
    'a pair of\n'
    'pairs of\n'
    'power wristguards\n'
    'power wristguards\n'
    '$Skill_Desc_01\n'
    'Increases max HP.\n'
    '$UI_OK\n'
    'OK\n'
    '$Tag_Only\n'
    '<cf>\n'
    '$Empty_Block\n'
    '$Greeting\n'
    'Hello there friend\n'
)
check('detect_format resident', E.detect_format(RES) == 'resident')
check('detect_format kv', E.detect_format('A=1\nB=2\n# c\nC=3\n') == 'kv')
check('check_line bắt thiếu <cf>', 'lệch_thẻ' in E.check_line('Go<cf>now', 'Đi now'))
check('check_line bắt thiếu tag rỗng <>', 'lệch_thẻ' in E.check_line('A<>B', 'AB'))
check('extract tag resident <count=0>/<cf>/<>', E.extract_placeholders('HP <count=0><cf><>') == ['<count=0>', '<cf>', '<>'])
doc = E.parse_doc(RES)
check('parse_doc fmt=resident', doc.fmt == 'resident')
uids = [u for u, _ in doc.pairs]
check('uid theo KEY#idx', uids[:3] == ['$Item_E_ACC_0001#0', '$Item_E_ACC_0001#1', '$Item_E_ACC_0001#2'], str(uids[:3]))
check('block rỗng -> 0 đơn vị', '$Empty_Block#0' not in uids)
check('số đơn vị dịch = 9', len(doc.pairs) == 9, str(len(doc.pairs)))
check('round-trip serialize(vals={}) == gốc', doc.serialize({}) == RES)
# serialize có thay bản dịch + giữ cấu trúc block
out_txt = doc.serialize({'$Item_E_ACC_0001#0': 'Bao Tay Sức Mạnh', '$Greeting#0': 'Xin chào bạn'})
check('serialize thay đúng dòng', 'Bao Tay Sức Mạnh\na pair of\n' in out_txt and 'Xin chào bạn\n' in out_txt)
check('serialize giữ header US', out_txt.startswith('US\n$Item_E_ACC_0001\n'))
check('serialize ép 1-dòng (loại \\n trong vi)', 'X Y' in doc.serialize({'$UI_OK#0': 'X\nY'}))

# end-to-end dịch file resident bằng MockProvider
workr = tempfile.mkdtemp(prefix='dich_resident_')
try:
    src = os.path.join(workr, 'Resident.txt'); out = os.path.join(workr, 'Resident_VI.txt')
    open(src, 'w', encoding='utf-8').write(RES)
    cfg = dict(src=src, out=out, keys=['k'], model='m', models=['m'], workers=4,
               maxlines=4, maxchars=8000, retries=3, rounds=4, max_tokens=8192,
               temperature=0.3, timeout=30, sysprompt='T')
    st0 = E.resume_status(src, out)
    check('resume_status resident total=9', st0['total'] == 9 and st0['done'] == 0, str(st0))
    evts = run_with_provider(cfg, MockProvider())
    res = open(out, encoding='utf-8').read()
    fin = [e for e in evts if e['type'] == 'finished']
    check('resident dịch xong (ok)', fin and fin[-1]['status'] == 'ok', str(fin[-1] if fin else None))
    check('resident output vẫn là format resident', E.detect_format(res) == 'resident')
    check('resident dịch nội dung (VI_)', 'VI_Power Wristguards\n' in res and 'VI_Hello there friend\n' in res)
    check('resident giữ thẻ <cf> nguyên', '$Tag_Only\n<cf>\n' in res)
    check('resident giữ cấu trúc multi-line (5 dòng)', 'VI_Power Wristguards\nVI_a pair of\nVI_pairs of\n' in res)
    check('resident giữ block rỗng', '$Empty_Block\n$Greeting\n' in res)
    st1 = E.resume_status(src, out)
    check('resident resume done==total', st1['done'] == st1['total'] and st1['total'] == 9, str(st1))
    rows, stt = E.build_preview_rows(src, out)
    # tag-only '<cf>' có vi==en -> preview xếp 'pending' (heuristic sẵn có, giống KV); done=8, không 'bad'
    check('preview rows resident', len(rows) == 9 and stt['total'] == 9 and stt['bad'] == 0, str(stt))
finally:
    shutil.rmtree(workr, ignore_errors=True)

# ---------------------------------------------------------------------------
print('\n%s  PASS=%d  FAIL=%d' % ('='*40, PASS, FAIL))
sys.exit(1 if FAIL else 0)
