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
print('\n[11] Byte: so sánh byte gốc/dịch + ép byte không vượt')
check('utf8_len ASCII', E.utf8_len('abc') == 3)
check('utf8_len dấu tiếng Việt', E.utf8_len('á') == 2 and E.utf8_len('Đồng ý') == 10, str(E.utf8_len('Đồng ý')))
check('utf8_len None/rỗng', E.utf8_len('') == 0 and E.utf8_len(None) == 0)

# check_line: luật byte chỉ áp khi byte_limit=True
check('check_line không xét byte khi tắt', E.check_line('OK', 'Đồng ý') == [])
check('check_line byte_limit bắt vượt', any('vượt_byte' in x for x in E.check_line('OK', 'Đồng ý', byte_limit=True)),
      str(E.check_line('OK', 'Đồng ý', byte_limit=True)))
check('check_line byte_limit không báo khi vi <= en', E.check_line('Hello world', 'Chao', byte_limit=True) == [])
check('check_line byte_limit vẫn bắt lỗi placeholder', 'lệch_{biến}' in E.check_line('Hi {0}', 'Chào', byte_limit=True))

# build_user_prompt: nhúng max_bytes + hướng dẫn khi item có ngân sách byte
up_b = E.build_user_prompt([{'id': 0, 'en': 'Start', 'placeholders': [], 'max_bytes': 5}])
pl_b = json.loads(up_b.rsplit('\n\n', 1)[-1])
check('build_user_prompt nhúng max_bytes', pl_b[0].get('max_bytes') == 5, str(pl_b))
check('build_user_prompt có hướng dẫn byte', 'max_bytes' in up_b and 'byte' in up_b.lower())
up_nb = E.build_user_prompt([{'id': 0, 'en': 'Start', 'placeholders': []}])
check('build_user_prompt KHÔNG có max_bytes khi không ngân sách',
      'max_bytes' not in json.loads(up_nb.rsplit('\n\n', 1)[-1])[0] and 'max_bytes' not in up_nb)

# build_preview_rows: thêm cột byte + thống kê 'over'
workb = tempfile.mkdtemp(prefix='dich_byte_')
try:
    srcb = os.path.join(workb, 'in.txt'); outb = os.path.join(workb, 'in_VI.txt')
    open(srcb, 'w', encoding='utf-8').write('A=OK\nB=Hello world here\nC=Quit\n')
    open(outb, 'w', encoding='utf-8').write('A=Đồng ý\nB=Thoát\nC=Quit\n')   # A vượt byte; B ngắn hơn; C==EN
    rows, st = E.build_preview_rows(srcb, outb)
    rmap = {r[0]: r for r in rows}
    check('preview rows 6 cột (key,en,vi,status,en_b,vi_b)', len(rows[0]) == 6, str(rows[0]))
    check('preview byte EN/VI đúng', rmap['A'][4] == E.utf8_len('OK') and rmap['A'][5] == E.utf8_len('Đồng ý'),
          '%s/%s' % (rmap['A'][4], rmap['A'][5]))
    check('preview đếm over=1 (chỉ A vượt)', st['over'] == 1, str(st))
    check('preview byte_limit TẮT -> A không bị nghi lỗi', rmap['A'][3] == 0, str(rmap['A']))
    rows2, st2 = E.build_preview_rows(srcb, outb, byte_limit=True)
    r2map = {r[0]: r for r in rows2}
    check('preview byte_limit BẬT -> A nghi lỗi (status 2)', r2map['A'][3] == 2, str(r2map['A']))
    check('preview byte_limit B (ngắn hơn) vẫn ok', r2map['B'][3] == 0, str(r2map['B']))
finally:
    shutil.rmtree(workb, ignore_errors=True)

# end-to-end: byte_limit BẬT, mock luôn làm vi DÀI hơn -> gửi max_bytes + còn dòng vượt byte
workb2 = tempfile.mkdtemp(prefix='dich_byte_e2e_')
try:
    src2 = os.path.join(workb2, 'in.txt'); out2 = os.path.join(workb2, 'in_VI.txt')
    open(src2, 'w', encoding='utf-8').write('\n'.join('L%d=Line %d here' % (i, i) for i in range(6)) + '\n')
    seen_prompts = []
    class _CapProv(MockProvider):
        def call(self, model, key, system, user):
            seen_prompts.append(user); return super().call(model, key, system, user)
    cfgb = dict(src=src2, out=out2, keys=['k'], model='m', models=['m'], workers=3,
                maxlines=4, maxchars=8000, retries=2, rounds=2, max_tokens=8192,
                temperature=0.3, timeout=30, sysprompt='T', byte_limit=True)
    evb = run_with_provider(cfgb, _CapProv())
    finb = [e for e in evb if e['type'] == 'finished']
    check('byte_limit: gửi max_bytes trong payload', any('"max_bytes"' in p for p in seen_prompts))
    check('byte_limit: còn dòng vượt byte (mock không rút được)', finb and finb[-1]['bad'] > 0, str(finb[-1] if finb else None))
    # cùng input, byte_limit TẮT -> KHÔNG còn nghi lỗi (mock VI_ hợp lệ placeholder)
    out3 = os.path.join(workb2, 'in2_VI.txt'); cfgn = dict(cfgb); cfgn['out'] = out3; cfgn['byte_limit'] = False
    evn = run_with_provider(cfgn, MockProvider())
    finn = [e for e in evn if e['type'] == 'finished']
    check('byte_limit TẮT: sạch lỗi (bad=0)', finn and finn[-1]['bad'] == 0, str(finn[-1] if finn else None))
finally:
    shutil.rmtree(workb2, ignore_errors=True)

# ---------------------------------------------------------------------------
print('\n[12] Tự giảm max_tokens khi vượt trần OUTPUT của model (400)')
# thông báo lỗi thật của router (Anthropic-style) khi max_tokens vượt trần model
B400 = ('{"error":{"message":"[claude/claude-opus-4-8] [400]: {\\"type\\":\\"error\\",\\"error\\":'
        '{\\"type\\":\\"invalid_request_error\\",\\"message\\":\\"max_tokens: 1000000 > 128000, '
        'which is the maximum allowed number of output tokens for claude-opus-4-8\\"}}"}}')
check('parse_max_tokens_cap Anthropic > 128000', E.parse_max_tokens_cap(B400) == 128000, str(E.parse_max_tokens_cap(B400)))
check('parse_max_tokens_cap OpenAI at most', E.parse_max_tokens_cap('supports at most 16384 completion tokens') == 16384)
check('parse_max_tokens_cap maximum is', E.parse_max_tokens_cap('maximum allowed is 4096 tokens') == 4096)
check('parse_max_tokens_cap không có số -> None', E.parse_max_tokens_cap('bad request') is None)

# _max_tokens_cap_from_error: chỉ áp cho lỗi max_tokens/output token (KHÔNG đụng context-length đầu vào)
_pp = E.OpenAIProvider('http://x'); _pp.max_tokens = 1000000
check('cap_from_error: max_tokens output -> trả trần', _pp._max_tokens_cap_from_error(B400) == 128000)
check('cap_from_error: lỗi context-length đầu vào -> None (không đụng)',
      _pp._max_tokens_cap_from_error('maximum context length is 8192 tokens') is None)
check('cap_from_error: trần >= max hiện tại -> None',
      E.OpenAIProvider('http://x')._max_tokens_cap_from_error('max_tokens 999 > 200000 output tokens') is None)

# E2E _post: 400 vượt trần -> TỰ giảm max_tokens + raise Transient (để translate_batch thử lại)
_pc = E.OpenAIProvider('http://x', debug=False); _pc.max_tokens = 1000000
_pc._client = _FakeClient(_FakeResp(400, B400))
_emsg = ''
try: _pc.call('cc/claude-opus-4-8', 'k', 's', 'u')
except E.Transient as e: _emsg = str(e)
check('auto-clamp: giảm max_tokens còn 128000', _pc.max_tokens == 128000, str(_pc.max_tokens))
check('auto-clamp: Transient báo đã giảm', 'đã giảm' in _emsg, _emsg)

# 400 thường (không liên quan max_tokens) -> KHÔNG đụng max_tokens
_pc2 = E.OpenAIProvider('http://x'); _pc2.max_tokens = 5000
_pc2._client = _FakeClient(_FakeResp(400, 'generic bad request'))
try: _pc2.call('m', 'k', 's', 'u')
except Exception: pass
check('400 thường giữ nguyên max_tokens', _pc2.max_tokens == 5000, str(_pc2.max_tokens))

# test_connection: tự phục hồi (clamp rồi thử lại) -> báo OK + đã tự giảm
class _SeqClient:
    def __init__(self, resps): self._resps = list(resps); self.i = 0
    def post(self, *a, **k):
        r = self._resps[min(self.i, len(self._resps) - 1)]; self.i += 1; return r
    def get(self, *a, **k): return self._resps[0]
    def close(self): pass
_ok_json = {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}
_pt = E.OpenAIProvider('http://x'); _pt.max_tokens = 1000000
_pt._client = _SeqClient([_FakeResp(400, B400), _FakeResp(200, '{}', jsonobj=_ok_json)])
_ok, _msg = E.test_connection(_pt, 'k', 'm')
check('test_connection tự phục hồi sau clamp', _ok and 'đã tự giảm max_tokens' in _msg, '%s | %s' % (_ok, _msg))

# --- VƯỢT CONTEXT WINDOW (tổng input+output > cửa sổ, vd 9Router 128000) -> giảm max_tokens chừa chỗ input ---
CTX400 = ('{"error":{"message":"This model\'s maximum context length is 128000 tokens. However, you '
          'requested 130050 tokens (2050 in the messages, 128000 in the completion). Please reduce the '
          'length of the messages or completion.","type":"invalid_request_error"}}')
check('parse_max_tokens_cap đọc trần ngữ cảnh', E.parse_max_tokens_cap(CTX400) == 128000, str(E.parse_max_tokens_cap(CTX400)))
check('parse_max_tokens_cap "context window of N" (không có max)', E.parse_max_tokens_cap('exceeds the context window of 128000 tokens') == 128000)
_pcx = E.OpenAIProvider('http://x'); _pcx.max_tokens = 128000
check('context_overflow -> nửa cửa sổ', _pcx._context_overflow_cap_from_error(CTX400) == 64000, str(_pcx._context_overflow_cap_from_error(CTX400)))
check('context_overflow: max_tokens đã nhỏ -> None (do input to)',
      E.OpenAIProvider('http://x', max_tokens=4096)._context_overflow_cap_from_error(CTX400) is None)
check('context_overflow: lỗi không phải ngữ cảnh -> None', _pcx._context_overflow_cap_from_error('bad request') is None)
# E2E _post: 400 vượt ngữ cảnh -> giảm max_tokens + raise Transient
_pce = E.OpenAIProvider('http://x', debug=False); _pce.max_tokens = 128000
_pce._client = _FakeClient(_FakeResp(400, CTX400))
_emc = ''
try: _pce.call('m', 'k', 's', 'u')
except E.Transient as e: _emc = str(e)
check('auto-fix ngữ cảnh: giảm max_tokens còn 64000', _pce.max_tokens == 64000, str(_pce.max_tokens))
check('auto-fix ngữ cảnh: Transient báo đã giảm', 'đã giảm' in _emc and 'context window' in _emc, _emc)
# test_connection tự phục hồi sau khi giảm vì vượt ngữ cảnh
_ptc = E.OpenAIProvider('http://x'); _ptc.max_tokens = 128000
_ptc._client = _SeqClient([_FakeResp(400, CTX400), _FakeResp(200, '{}', jsonobj=_ok_json)])
_ok2, _msg2 = E.test_connection(_ptc, 'k', 'm')
check('test_connection phục hồi sau vượt ngữ cảnh', _ok2 and 'đã tự giảm max_tokens' in _msg2, '%s | %s' % (_ok2, _msg2))

# ---------------------------------------------------------------------------
print('\n[13] Context 1M: header anthropic-beta')
check('build_anthropic_beta rỗng', E.build_anthropic_beta({}) == '')
check('build_anthropic_beta context_1m', E.build_anthropic_beta({'context_1m': True}) == 'context-1m-2025-08-07')
check('build_anthropic_beta thô (tách , space)', E.build_anthropic_beta({'anthropic_beta': 'foo, bar baz'}) == 'foo,bar,baz')
check('build_anthropic_beta bỏ trùng', E.build_anthropic_beta({'context_1m': True, 'anthropic_beta': 'context-1m-2025-08-07'}) == 'context-1m-2025-08-07')
check('CONTEXT_1M_BETA đúng giá trị', E.CONTEXT_1M_BETA == 'context-1m-2025-08-07')

# header thực sự gắn anthropic-beta khi bật, và KHÔNG gắn khi tắt
_pb = E.OpenAIProvider('http://x', anthropic_beta='context-1m-2025-08-07')
check('OpenAI headers có anthropic-beta', _pb.headers('K') == {'Authorization': 'Bearer K', 'anthropic-beta': 'context-1m-2025-08-07'}, str(_pb.headers('K')))
_pa = E.AnthropicProvider('http://x', anthropic_beta='context-1m-2025-08-07')
check('Anthropic headers có anthropic-beta + x-api-key',
      _pa.headers('K') == {'x-api-key': 'K', 'anthropic-version': '2023-06-01', 'anthropic-beta': 'context-1m-2025-08-07'}, str(_pa.headers('K')))
check('OpenAI headers KHÔNG có beta khi tắt', 'anthropic-beta' not in E.OpenAIProvider('http://x').headers('K'))
check('make_provider context_1m -> anthropic_beta', E.make_provider({'provider': 'openai', 'base_url': 'http://x', 'context_1m': True}).anthropic_beta == E.CONTEXT_1M_BETA)
check('make_provider mặc định không beta', E.make_provider({'provider': 'openai', 'base_url': 'http://x'}).anthropic_beta == '')

# ---------------------------------------------------------------------------
# [14] Newline thật trong value — ghép dòng vật lý + check đếm newline
# Bug cũ: parse_pairs_text cắt txt.split('\n') -> value có \n thật bị mất phần sau.
# Fix: ghép dòng continuation; Doc.serialize ghi NHIỀU DÒNG; check_line đếm newline thật.
print('\n[14] Newline trong value (ghép dòng vật lý)')

# --- parse_pairs_text: ghép dòng ---
_raw, _pairs = E.parse_pairs_text('K=A\n  D\nB=C')
check('parse_pairs_text ghép dòng continuation',
      _pairs == [('K', 'A\n  D'), ('B', 'C')], str(_pairs))
check('parse_pairs_text giữ raw đầy đủ (3 dòng)', _raw == ['K=A', '  D', 'B=C'], str(_raw))

# comment phá vỡ continuation
_raw2, _pairs2 = E.parse_pairs_text('K=A\n# cmt\nB=C')
check('comment phá vỡ continuation',
      _pairs2 == [('K', 'A'), ('B', 'C')], str(_pairs2))

# dòng rỗng giữ \n trong value
_raw3, _pairs3 = E.parse_pairs_text('K=A\n\nB=C')
check('dòng rỗng trong value giữ \\n',
      _pairs3 == [('K', 'A\n'), ('B', 'C')], str(_pairs3))

# dòng thừa không thuộc KEY nào (trước KEY đầu tiên) -> bỏ
_raw4, _pairs4 = E.parse_pairs_text('orphan\nK=A\nB=C')
check('dòng thừa trước KEY đầu -> bỏ',
      _pairs4 == [('K', 'A'), ('B', 'C')], str(_pairs4))

# --- Doc.serialize kv: ghi NHIỀU DÒNG vật lý ---
_txt = '# cmt\nK=A\n  D\nK2=X\n'
_doc = E.parse_doc(_txt)
check('parse_doc kv ghép continuation', _doc.pairs == [('K', 'A\n  D'), ('K2', 'X')], str(_doc.pairs))
_out_txt = _doc.serialize({'K': 'X\nY', 'K2': 'Z'})
check('serialize ghi NHIỀU DÒNG vật lý đúng vị trí',
      _out_txt == '# cmt\nK=X\nY\n  D\nK2=Z\n', repr(_out_txt))
# byte-for-byte với file gốc (vals={} -> giữ nguyên)
_out_orig = _doc.serialize({})
check('serialize({}) khớp byte-for-byte với input (regression file 1-dòng value)',
      _out_orig == _txt, repr(_out_orig))

# vi có \r -> thay bằng space
_out_cr = E.parse_doc('K=A\n').serialize({'K': 'X\rY'})
check('serialize thay \\r bằng space (an toàn)', _out_cr == 'K=X Y\n', repr(_out_cr))

# --- check_line: đếm newline thật ---
check('check_line lệch newline thật',
      'lệch_\\n' in E.check_line('A\nB', 'X Y'),
      str(E.check_line('A\nB', 'X Y')))
check('check_line newline khớp -> OK',
      E.check_line('A\nB', 'X\nY') == [], str(E.check_line('A\nB', 'X\nY')))
# \\n literal (2 ký tự) KHÔNG tính là newline thật
check('check_line \\n LITERAL (2 ký tự) KHÔNG tính là newline thật',
      E.check_line(r'A\nB', r'X\nY') == [], str(E.check_line(r'A\nB', r'X\nY')))

# --- E2E: round-trip + resume + tự sửa + byte_limit ---
work14 = tempfile.mkdtemp(prefix='dich_nl_')
try:
    src14 = os.path.join(work14, 'in.txt'); out14 = os.path.join(work14, 'in_VI.txt')

    # (11) round-trip: dịch file có value 2 dòng -> file output giữ số dòng vật lý
    open(src14, 'w', encoding='utf-8').write(
        '# cmt\nTUT=A\nB\nSAME=SAME\nE=\nF=Single line value\n')
    cfg14 = dict(src=src14, out=out14, keys=['k1'], model='m', models=['m'],
                 workers=4, maxlines=4, maxchars=8000, retries=2, rounds=4,
                 max_tokens=8192, temperature=0.3, timeout=30, sysprompt='TEST PROMPT')
    evts14 = run_with_provider(cfg14, MockProvider())
    res14 = open(out14, encoding='utf-8').read()
    # TUT value 2 dòng -> serialize ghi 2 dòng vật lý (KEY + 1 newline + value 2 dòng)
    lines14 = res14.split('\n')
    # đếm dòng bắt đầu bằng 'TUT=' (chỉ dòng key, không tính dòng continuation)
    tut_key_lines = [i for i, l in enumerate(lines14) if l.startswith('TUT=')]
    check('round-trip TUT giữ key ở dòng riêng', len(tut_key_lines) == 1, str(tut_key_lines))
    tut_idx = tut_key_lines[0]
    # mock ghép 'VI_A\nB' (1 chuỗi có \n); serialize ghi thành 1 dòng vật lý 'TUT=VI_A\nB'
    # -> split('\n') ra ['TUT=VI_A', 'B']; dòng tiếp theo (vật lý) = 'B'
    check('round-trip TUT có value trên dòng tiếp theo (ghép dòng)',
          lines14[tut_idx] == 'TUT=VI_A' and lines14[tut_idx + 1] == 'B',
          repr(lines14[tut_idx:tut_idx + 2]))
    check('round-trip SAME giữ nguyên', any(l == 'SAME=SAME' for l in lines14))
    check('round-trip F (value đơn) không bị ghép',
          any(l == 'F=VI_Single line value' for l in lines14))
    check('round-trip comment giữ', lines14[0] == '# cmt')

    # (12) resume: file đã dịch 1 phần có value 2 dòng -> load_progress giữ \n
    out14b = os.path.join(work14, 'in_VI_b.txt')
    open(src14, 'w', encoding='utf-8').write('A=Line one\nLine two\nB=Other\n')
    open(out14b, 'w', encoding='utf-8').write('A=VI_Line one\nVI_Line two\n')  # đã dịch A
    open(out14b + '.done.txt', 'w', encoding='utf-8').write('A\n')
    cfg14b = dict(cfg14); cfg14b['out'] = out14b
    evts14b = run_with_provider(cfg14b, MockProvider())
    res14b = open(out14b, encoding='utf-8').read()
    # A đã dịch giữ \n; B được dịch mới
    check('resume giữ \\n trong value đã dịch sẵn',
          'A=VI_Line one\nVI_Line two\n' in res14b, repr(res14b))
    check('resume dịch tiếp B', 'B=VI_Other' in res14b)
    log14b = [e for e in evts14b if e['type'] == 'log']
    check('resume có log "đã có N dòng dịch trước"',
          any('Resume' in e.get('msg', '') and '1' in e.get('msg', '') for e in log14b),
          str([e.get('msg', '') for e in log14b[:3]]))

    # (13) tự sửa: AI trả value lệch newline -> dịch lại tự sửa
    class MockDropNewline(MockProvider):
        """Lần đầu trả value không có \n; các lần sau trả đúng (giả lập AI sai rồi tự sửa)."""
        def __init__(self, **kw):
            super().__init__(**kw); self.bad_once = True
        def call(self, model, key, system, user):
            with self.lock:
                self.calls += 1; n = self.calls
            payload = json.loads(user.rsplit('\n\n', 1)[-1])
            if self.bad_once and any('\n' in it['en'] for it in payload):
                self.bad_once = False
                # Trả value đã GHÉP thành 1 dòng (lệch newline)
                out = [{'id': it['id'],
                        'vi': it['en'].replace('\n', ' ').replace('A', 'VI_A').replace('B', 'VI_B')
                              if '\n' in it['en']
                              else ('VI_' + it['en'] if it['en'] else it['en'])}
                       for it in payload]
                return json.dumps(out, ensure_ascii=False)
            return super().call(model, key, system, user)
    src14c = os.path.join(work14, 'in_c.txt'); out14c = os.path.join(work14, 'in_c_VI.txt')
    open(src14c, 'w', encoding='utf-8').write('TUT=A\nB\n')
    cfg14c = dict(cfg14); cfg14c['src'] = src14c; cfg14c['out'] = out14c
    cfg14c['rounds'] = 3
    evts14c = run_with_provider(cfg14c, MockDropNewline())
    res14c = open(out14c, encoding='utf-8').read()
    # Round 1: MockDropNewline trả 'VI_A VI_B' (1 dòng, lệch \n) -> check_line báo lỗi
    # Round 2 (tự sửa): super().call() trả 'VI_A\nB' (đúng \n) -> ghi 'TUT=VI_A\nB'
    check('tự sửa: round retry TUT có \\n đúng',
          'TUT=VI_A\nB' in res14c, repr(res14c))
    log14c = [e.get('msg', '') for e in evts14c if e['type'] == 'log']
    check('tự sửa: có log Sửa-v',
          any('Sửa-v' in m for m in log14c), str(log14c[:5]))

    # (14) byte_limit: \n thật tính 1 byte UTF-8 (đúng thực tế, không phải 2)
    # value 'A\nB' = 3 byte; 'VI_A\nVI_B' = 8 byte > 3 -> vượt
    src14d = os.path.join(work14, 'in_d.txt'); out14d = os.path.join(work14, 'in_d_VI.txt')
    open(src14d, 'w', encoding='utf-8').write('S=Short\n')
    cfg14d = dict(cfg14); cfg14d['src'] = src14d; cfg14d['out'] = out14d
    cfg14d['byte_limit'] = True
    cfg14d['rounds'] = 2
    # MockProvider trả 'VI_Short\n' = 9 byte > 5 byte -> vượt byte
    evts14d = run_with_provider(cfg14d, MockProvider())
    res14d = open(out14d, encoding='utf-8').read()
    # check_line có 'vượt_byte' -> ghi nhưng engine best-effort giữ value
    check('byte_limit \\n tính 1 byte (vi vẫn được ghi)',
          'S=VI_Short' in res14d, repr(res14d))
    # build_preview_rows: en_bytes/vi_bytes tính đúng \n
    rows14, stats14 = E.build_preview_rows(src14c, out14c, byte_limit=False)
    tut_row = next((r for r in rows14 if r[0] == 'TUT'), None)
    check('preview_rows TUT en_bytes=3 (A\\nB)', tut_row and tut_row[4] == 3, str(tut_row))
    check('preview_rows TUT vi_bytes=8 (VI_A\\nVI_B)', tut_row and tut_row[5] == 8, str(tut_row))
finally:
    shutil.rmtree(work14, ignore_errors=True)

# ---------------------------------------------------------------------------
print('\n%s  PASS=%d  FAIL=%d' % ('='*40, PASS, FAIL))
sys.exit(1 if FAIL else 0)
