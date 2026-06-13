#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
#  test_engine.py — Test engine HEADLESS (không gọi mạng) bằng MockProvider.
#  Chạy:  python3 tests/test_engine.py
# ============================================================================
import os, sys, json, threading, tempfile, shutil, io, contextlib

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
check('read_text path thư mục -> rỗng (không crash)', E.read_text(os.path.dirname(os.path.abspath(__file__))) == '')
check('resume_status path thư mục -> total 0', E.resume_status(os.path.dirname(os.path.abspath(__file__)), '') == {'total':0,'done':0,'todo':0})

# ---------------------------------------------------------------------------
print('\n[2] Provider builders (không gọi mạng)')
op = E.OpenAIProvider('https://x.y/v1')
check('OpenAI endpoint', op.endpoint() == 'https://x.y/v1/chat/completions')
check('OpenAI header Bearer', op.headers('K') == {'Authorization': 'Bearer K'})
ob = op.build_body('m', 'SYS', 'USR')
check('OpenAI body messages', ob['messages'][0]['role']=='system' and ob['messages'][1]['content']=='USR')
check('OpenAI body max_tokens', 'max_tokens' in ob)
check('OpenAI body stream=False (router mặc định SSE -> ép tắt)', ob.get('stream') is False)
check('OpenAI có temperature khi đặt', ob.get('temperature') == op.temperature)
_opn = E.OpenAIProvider('https://x.y'); _opn.temperature = None
check('OpenAI BỎ temperature khi None (model codex/o-series)', 'temperature' not in _opn.build_body('m', 's', 'u'))
_apn = E.AnthropicProvider('https://x'); _apn.temperature = None
check('Anthropic BỎ temperature khi None', 'temperature' not in _apn.build_body('m', 's', 'u'))
check('make_provider send_temperature=False -> temp None',
      E.make_provider({'provider': 'openai', 'base_url': 'http://x', 'send_temperature': False}).temperature is None)
check('make_provider mặc định vẫn gửi temperature',
      E.make_provider({'provider': 'openai', 'base_url': 'http://x', 'temperature': 0.5}).temperature == 0.5)
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
print('\n[8] Dịch cả thư mục (folder) — đa file, đa định dạng')
# norm_exts: chuẩn hóa chuỗi/list đuôi file
check('norm_exts trống -> None', E.norm_exts('') is None and E.norm_exts(None) is None)
check('norm_exts chuỗi hỗn hợp', E.norm_exts('.txt, json *.csv') == {'.txt', '.json', '.csv'})
check('norm_exts list', E.norm_exts(['TXT', '.Json']) == {'.txt', '.json'})
check('default_out_folder song song _vi', E.default_out_folder('/a/b/text_en') == '/a/b/text_en_vi')
check('default_out_folder bỏ / cuối', E.default_out_folder('/a/b/text_en/') == '/a/b/text_en_vi')

workf = tempfile.mkdtemp(prefix='dich_folder_')
try:
    # cây thư mục: 2 file .txt (1 ở thư mục con), 1 file .json, 1 file .md (bỏ qua khi lọc .txt)
    os.makedirs(os.path.join(workf, 'src', 'sub'))
    open(os.path.join(workf, 'src', 'a.txt'), 'w', encoding='utf-8').write('K1=Hello world here\nK2=Press {0} now\n')
    open(os.path.join(workf, 'src', 'sub', 'b.txt'), 'w', encoding='utf-8').write('M1=Another line of text\n')
    open(os.path.join(workf, 'src', 'c.json'), 'w', encoding='utf-8').write('J1=Some json style value\n')
    open(os.path.join(workf, 'src', 'note.md'), 'w', encoding='utf-8').write('D1=Ignore me please now\n')
    open(os.path.join(workf, 'src', 'a.txt.done.txt'), 'w', encoding='utf-8').write('K1\n')   # artifact -> bỏ
    src_dir = os.path.join(workf, 'src')

    files = E.list_folder_files(src_dir)
    check('list_folder_files bỏ artifact .done.txt', 'a.txt.done.txt' not in files)
    check('list_folder_files đệ quy + sort', files == ['a.txt', 'c.json', 'note.md', os.path.join('sub', 'b.txt')], str(files))
    only_txt = E.list_folder_files(src_dir, '.txt')
    check('list_folder_files lọc .txt', only_txt == ['a.txt', os.path.join('sub', 'b.txt')], str(only_txt))
    check('list_folder_files path không phải thư mục -> []', E.list_folder_files(os.path.join(src_dir, 'a.txt')) == [])

    out_dir = os.path.join(workf, 'src_vi')
    ov0 = E.folder_overview(src_dir, out_dir, '.txt')
    check('folder_overview ban đầu have_out=0', ov0 == {'files': 2, 'have_out': 0}, str(ov0))

    # end-to-end: dịch chỉ .txt bằng MockProvider (monkeypatch make_provider)
    _orig_make = E.make_provider
    E.make_provider = lambda cfg: MockProvider()
    try:
        evts = []
        E.run_folder_translation(dict(src=src_dir, out=out_dir, exts='.txt', keys=['k'], model='m',
                                      models=['m'], workers=4, maxlines=5, maxchars=8000, retries=2,
                                      rounds=3, max_tokens=8192, temperature=0.3, timeout=30, sysprompt='T'),
                                 evts.append, threading.Event())
    finally:
        E.make_provider = _orig_make

    fin = [e for e in evts if e['type'] == 'finished']
    check('folder finished ok', fin and fin[-1]['status'] == 'ok' and len(fin) == 1, str(fin))
    check('folder finished 2/2 file', fin and fin[-1]['done'] == 2 and fin[-1]['total'] == 2, str(fin[-1] if fin else None))
    check('có folder_init', any(e['type'] == 'folder_init' and e['n_files'] == 2 for e in evts))
    check('có folder_file start+done', sum(1 for e in evts if e['type'] == 'folder_file') == 4)
    # output đúng cây thư mục + chỉ .txt được dịch
    check('output a.txt tồn tại', os.path.isfile(os.path.join(out_dir, 'a.txt')))
    check('output sub/b.txt giữ cây thư mục', os.path.isfile(os.path.join(out_dir, 'sub', 'b.txt')))
    check('KHÔNG dịch c.json (lọc .txt)', not os.path.isfile(os.path.join(out_dir, 'c.json')))
    res_a = open(os.path.join(out_dir, 'a.txt'), encoding='utf-8').read()
    check('a.txt dịch có VI_', 'K1=VI_Hello world here' in res_a)
    check('a.txt giữ placeholder', 'K2=Press {0} now' in res_a)
    ov1 = E.folder_overview(src_dir, out_dir, '.txt')
    check('folder_overview sau dịch have_out=2', ov1 == {'files': 2, 'have_out': 2}, str(ov1))

    # resume: chạy lại -> vẫn ok, không lỗi (file đã xong nhận diện qua output)
    E.make_provider = lambda cfg: MockProvider()
    try:
        evts2 = []
        E.run_folder_translation(dict(src=src_dir, out=out_dir, exts='txt', keys=['k'], model='m',
                                      models=['m'], workers=4, maxlines=5, maxchars=8000, retries=2,
                                      rounds=3, max_tokens=8192, temperature=0.3, timeout=30, sysprompt='T'),
                                 evts2.append, threading.Event())
    finally:
        E.make_provider = _orig_make
    fin2 = [e for e in evts2 if e['type'] == 'finished']
    check('folder resume vẫn ok 2/2', fin2 and fin2[-1]['status'] == 'ok' and fin2[-1]['done'] == 2, str(fin2[-1] if fin2 else None))

    # thư mục rỗng (không khớp đuôi) -> finished error, không tạo file
    evtsE = []
    E.run_folder_translation(dict(src=src_dir, out=os.path.join(workf, 'none_vi'), exts='.xml',
                                  keys=['k'], model='m', models=['m'], workers=2, sysprompt='T'),
                             evtsE.append, threading.Event())
    finE = [e for e in evtsE if e['type'] == 'finished']
    check('folder không file khớp -> error', finE and finE[-1]['status'] == 'error', str(finE[-1] if finE else None))
finally:
    shutil.rmtree(workf, ignore_errors=True)

# ---------------------------------------------------------------------------
print('\n[9] Token: ước lượng + cap khi sinh prompt + nhận diện lỗi')
check('estimate_tokens rỗng', E.estimate_tokens('') == 0)
check('estimate_tokens ~ chars/4', E.estimate_tokens('a' * 400) == 100, str(E.estimate_tokens('a' * 400)))
_txt = '\n'.join('K%d=Line number %d here now' % (i, i) for i in range(50)) + '\n'
_st = E.sample_stats(_txt)
check('sample_stats lines=50', _st['lines'] == 50, str(_st))
check('sample_stats chars khớp', _st['chars'] == len(_txt))
check('sample_stats tokens>0 & sample<=total', _st['tokens'] > 0 and 0 < _st['sample_tokens'] <= _st['tokens'], str(_st))
check('sample_stats rỗng', E.sample_stats('') == {'lines': 0, 'chars': 0, 'tokens': 0, 'sample_tokens': 0})

check('is_token_limit_error context length', E.is_token_limit_error("This model's maximum context length is 8192 tokens"))
check('is_token_limit_error max_tokens', E.is_token_limit_error("max_tokens is too large: 1000000"))
check('is_token_limit_error too many tokens', E.is_token_limit_error("Too many tokens in request"))
check('is_token_limit_error âm tính', not E.is_token_limit_error("connection reset by peer"))

# gen_system_prompt GIỚI HẠN output max_tokens rồi KHÔI PHỤC
class _RecMaxTok(E.Provider):
    name = 'recmt'
    def __init__(self, **kw): super().__init__('http://mock', **kw); self.seen_mt = None
    def call(self, model, key, system, user): self.seen_mt = self.max_tokens; return '  GEN PROMPT  '
_p = _RecMaxTok(max_tokens=1000000)
_out = E.gen_system_prompt(_p, 'k', 'm', 'A=hello\nB=world', gen_max_tokens=4096)
check('gen_system_prompt cap output max_tokens', _p.seen_mt == 4096, str(_p.seen_mt))
check('gen_system_prompt khôi phục max_tokens', _p.max_tokens == 1000000, str(_p.max_tokens))
check('gen_system_prompt trả prompt (strip)', _out == 'GEN PROMPT', repr(_out))
_p2 = _RecMaxTok(max_tokens=2048)   # max_tokens nhỏ hơn cap -> giữ nguyên
E.gen_system_prompt(_p2, 'k', 'm', 'A=x', gen_max_tokens=4096)
check('gen_system_prompt giữ max_tokens khi đã nhỏ', _p2.seen_mt == 2048, str(_p2.seen_mt))
_p3 = _RecMaxTok(max_tokens=1000000)
E.gen_system_prompt(_p3, 'k', 'm', 'A=x')   # trần MẶC ĐỊNH (đủ rộng cho prompt giàu -> không cắt)
check('gen_system_prompt trần mặc định = 16384', _p3.seen_mt == 16384, str(_p3.seen_mt))

# is_truncated: phát hiện phản hồi bị cắt do chạm trần output
_op = E.OpenAIProvider('http://x')
check('OpenAI is_truncated finish_reason=length',
      _op.is_truncated({'choices': [{'finish_reason': 'length', 'message': {'content': 'x'}}]}))
check('OpenAI not truncated finish_reason=stop',
      not _op.is_truncated({'choices': [{'finish_reason': 'stop'}]}))
_anp = E.AnthropicProvider('http://x')
check('Anthropic is_truncated stop_reason=max_tokens', _anp.is_truncated({'stop_reason': 'max_tokens'}))
check('Anthropic not truncated stop_reason=end_turn', not _anp.is_truncated({'stop_reason': 'end_turn'}))

# ---------------------------------------------------------------------------
print('\n[10] Debug: in API trả về ra console khi lỗi (KHÔNG lộ API key)')
class _FakeResp:
    def __init__(self, code, text, jsonobj=None, raise_json=False):
        self.status_code = code; self.text = text; self._j = jsonobj; self._rj = raise_json
    def json(self):
        if self._rj: raise ValueError('not json')
        return self._j
class _FakeClient:
    def __init__(self, resp): self._resp = resp
    def post(self, url, headers=None, json=None, timeout=None): return self._resp
    def get(self, *a, **k): return self._resp
    def close(self): pass

def _capture_call(provider, resp):
    provider._client = _FakeClient(resp)   # tiêm client giả (bỏ qua property lazy)
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try: provider.call('m', 'SECRETKEY_DO_NOT_LEAK', 'sys', 'usr')
        except Exception: pass
    return buf.getvalue()

# HTTP 400 -> in mã lỗi + nguyên văn body, KHÔNG lộ key
s = _capture_call(E.OpenAIProvider('http://x', debug=True), _FakeResp(400, 'BODY_DETAIL_FROM_API'))
check('debug in nội dung API trả về', 'BODY_DETAIL_FROM_API' in s, s[:160])
check('debug in mã HTTP 400', 'HTTP 400' in s and 'API-DEBUG' in s)
check('debug KHÔNG lộ API key', 'SECRETKEY_DO_NOT_LEAK' not in s)

# debug TẮT -> không in gì
s_off = _capture_call(E.OpenAIProvider('http://x', debug=False), _FakeResp(400, 'MUST_NOT_PRINT'))
check('debug TẮT -> im lặng', s_off.strip() == '', repr(s_off[:80]))

# 200 nhưng body không phải JSON (router trả SSE/HTML) -> in no_json + body
s_nj = _capture_call(E.OpenAIProvider('http://x', debug=True), _FakeResp(200, 'NOT_JSON_SSE_DATA', raise_json=True))
check('debug no_json in body', 'NOT_JSON_SSE_DATA' in s_nj and 'no_json' in s_nj)

# 200 + JSON nhưng sai cấu trúc (thiếu choices) -> in parse lỗi + nguyên JSON
s_nc = _capture_call(E.OpenAIProvider('http://x', debug=True), _FakeResp(200, '{}', jsonobj={'weird': 'SHAPE_ABC'}))
check('debug no_content in JSON', 'SHAPE_ABC' in s_nc and 'parse' in s_nc.lower())

check('make_provider debug=True', E.make_provider({'provider': 'openai', 'base_url': 'http://x', 'debug': True}).debug is True)
check('make_provider debug mặc định False', E.make_provider({'provider': 'openai', 'base_url': 'http://x'}).debug is False)

# ---------------------------------------------------------------------------
print('\n%s  PASS=%d  FAIL=%d' % ('='*40, PASS, FAIL))
sys.exit(1 if FAIL else 0)
