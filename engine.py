#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
#  engine.py  —  KeyValue Game Localization AI Translator: engine dịch file KEY=text (EN -> VI).
#                KHÔNG phụ thuộc Qt.
#
#  - Mạng dùng httpx (connection pooling + keep-alive + HTTP/2 nếu có) -> nhanh hơn urllib
#    nhiều khi gọi hàng trăm lô (tái dùng TLS, không handshake lại mỗi request).
#    httpx tự dùng certifi -> không dính CERTIFICATE_VERIFY_FAILED trên macOS.
#  - Hỗ trợ 2 format API: OpenAI-compatible (/chat/completions) & Anthropic (/v1/messages).
#  - Dịch ĐA LUỒNG (ThreadPoolExecutor): chia lô, gửi JSON array [{id,en}] -> [{id,vi}].
#  - Tự kiểm & tự sửa placeholder, resume qua <out>.done.txt, xoay (model,key) + cooldown.
#  - Tự sinh system prompt từ tên game + mẫu text EN.
#
#  Giao tiếp với GUI qua MỘT callback emit(evt: dict). Không import PyQt -> test headless được.
#  Lớp GUI (app.py) bọc emit bằng pyqtSignal.
# ============================================================================
import os, json, time, re, threading
from concurrent.futures import ThreadPoolExecutor
import httpx

# ============================== PROMPT MẶC ĐỊNH ==============================
UNIVERSAL_RULES = (
    "Bạn là chuyên gia bản địa hóa game sang TIẾNG VIỆT tự nhiên, chuẩn game AAA.\n"
    "QUY TẮC BẮT BUỘC:\n"
    "- Bạn nhận một JSON array các mục [{\"id\":int,\"en\":\"...\"}]. Dịch phần \"en\" sang tiếng Việt.\n"
    "- GIỮ NGUYÊN tuyệt đối: {biến} {0} \\n \\r thẻ HTML <...> </...> [REDACTED] và mọi placeholder/ký hiệu điều khiển.\n"
    "  Số lượng và vị trí placeholder trong bản dịch PHẢI khớp bản gốc.\n"
    "- Dịch tự nhiên, đúng nghĩa, hợp văn cảnh; KHÔNG dịch máy từng từ.\n"
    "- Mục \"en\" rỗng/chỉ ký hiệu/mã -> giữ NGUYÊN.\n"
    "- KHÔNG giải thích, KHÔNG chú thích."
)
OUTPUT_REMINDER = (
    "=== ĐỊNH DẠNG TRẢ LỜI (BẮT BUỘC) ===\n"
    "CHỈ trả về một JSON array, KHÔNG markdown, KHÔNG ```json, KHÔNG giải thích:\n"
    "[{\"id\":0,\"vi\":\"...\"},{\"id\":1,\"vi\":\"...\"}]\n"
    "Đúng số mục, mỗi id một bản dịch."
)
GEN_META_SYS = (
    "Bạn là chuyên gia tạo SYSTEM PROMPT để bản địa hóa game sang tiếng Việt. "
    "Bạn nhận TÊN GAME và một mẫu text game (tiếng Anh, định dạng ID=nội_dung), rồi viết ra một "
    "system prompt tiếng Việt HOÀN CHỈNH để một AI khác dùng dịch toàn bộ game này thật nhất quán."
)
GEN_META_USER = (
    "Hãy phân tích rồi VIẾT một system prompt tiếng Việt đầy đủ, gồm:\n"
    "1. BỐI CẢNH GAME: đoán thể loại, không khí, tone phù hợp (dựa vào tên game + mẫu text).\n"
    "2. GLOSSARY: tên riêng/nhân vật/địa danh GIỮ NGUYÊN; thuật ngữ gameplay DỊCH THỐNG NHẤT (liệt kê EN -> VI).\n"
    "3. XƯNG HÔ & VĂN PHONG theo loại string (UI ngắn gọn; thoại tự nhiên; lore trang trọng...).\n"
    "4. QUY TẮC KỸ THUẬT: GIỮ NGUYÊN mọi {biến} <thẻ> \\n \\r [REDACTED]; chuỗi UI HOA giữ HOA; "
    "mục rỗng/ký hiệu giữ nguyên.\n\n"
    "CHỈ trả về NỘI DUNG system prompt (tiếng Việt), KHÔNG mở đầu, KHÔNG ```.\n"
)
TONES = {
    'Tự động (theo nội dung)': '',
    'Hành động / Bắn súng': 'Văn phong mạnh mẽ, gọn, kịch tính; thoại dứt khoát.',
    'Kinh dị / Hồi hộp': 'Văn phong rùng rợn, căng thẳng, u ám; tạo không khí sợ hãi.',
    'Nhập vai RPG / Giả tưởng': 'Văn phong sử thi, trang trọng, đậm chất giả tưởng; tên kỹ năng/vật phẩm nhất quán.',
    'Phiêu lưu / Giải đố': 'Văn phong nhẹ nhàng, tò mò, dẫn dắt khám phá.',
    'Anime / JRPG': 'Văn phong cảm xúc, trẻ trung, giàu biểu cảm; giữ sắc thái từng nhân vật.',
    'Hài hước': 'Văn phong vui nhộn, dí dỏm, chơi chữ hợp lý.',
    'Trinh thám / Hồ sơ mật': 'Văn phong lạnh, chính xác, hành chính, bí ẩn.',
    'Khoa học viễn tưởng': 'Văn phong hiện đại, chính xác, đậm chất công nghệ/khoa học.',
    'Thể thao / Đua xe': 'Văn phong nhanh, năng động, gọn rõ.',
}

# ============================== HÀM THUẦN (PURE) ==============================
RE_CURLY = re.compile(r'\{[^{}]*\}'); RE_TAG = re.compile(r'</?[a-zA-Z][^>]*>|<>')  # '<>' = tag rỗng (resident)
RE_REDACT = re.compile(r'\[[A-Z0-9 _\-]{2,}\]')
_PH_RE = re.compile(r'<[^>]*>|\{[^}]*\}|%[sdfSDF]|\\[nrt]')   # '<[^>]*>' bắt cả '<>' để gợi ý cho AI

def read_text(p):
    return open(p, encoding='utf-8-sig').read() if (p and os.path.exists(p)) else ''

def extract_placeholders(text):
    seen = []
    for m in _PH_RE.findall(text):
        if m not in seen: seen.append(m)
    return seen

def parse_pairs_text(txt):
    raw = txt.split('\n')
    if raw and raw[-1] == '': raw = raw[:-1]
    pairs = []
    for ln in raw:
        if not ln or ln.lstrip().startswith('#'): continue
        if '=' in ln:
            k, v = ln.split('=', 1); pairs.append((k, v))
    return raw, pairs

# ===================== ĐA-FORMAT I/O (KEY=VALUE  &  Resident $KEY-block) =====================
# Lõi gốc chỉ hiểu 'kv' (mỗi dòng KEY=VALUE). Thêm 'resident' (FF7 Rebirth Resident_TxtRes):
#   dòng đầu = header ngôn ngữ (vd 'US'); rồi từng block:  $KEY  +  0..n dòng nội dung,
#   mỗi dòng nội dung là 1 BIẾN THỂ độc lập (tên / mạo từ / số ít / số nhiều) -> DỊCH RIÊNG.
#   Bất biến vẫn là thẻ <...> (RE_TAG). Không có '=' phân tách -> không nạp thẳng vào parser KV.
# Trừu tượng chung: Doc.pairs = [(uid, en)] với uid DUY NHẤT; Doc.serialize(vals) dựng lại ĐÚNG format.
#   - kv:       uid = KEY (giữ NGUYÊN hành vi cũ; KEY trùng -> value cuối thắng).
#   - resident: uid = '<$KEY>#<chỉ_số_dòng>'  (KEY sạch [A-Za-z0-9_$], không chứa '#').
RE_RKEY = re.compile(r'^\$(?=[^\n]*[A-Za-z])[^\s=]+$')   # dòng KEY resident: '$' + có chữ cái, không space/'='

def detect_format(txt):
    """Đoán format từ nội dung: 'resident' nếu có >=3 dòng KEY đứng riêng và lấn át dòng KEY=VALUE."""
    n_key = n_kv = 0
    for ln in txt.split('\n'):
        if not ln or ln.lstrip().startswith('#'): continue
        if RE_RKEY.match(ln): n_key += 1
        elif '=' in ln: n_kv += 1
    return 'resident' if (n_key >= 3 and n_key >= n_kv) else 'kv'

class Doc:
    """Tài liệu locale đa-format. pairs=[(uid,en)] cho lõi dịch; serialize(vals) dựng lại đúng format gốc."""
    def __init__(self, fmt, payload, pairs):
        self.fmt = fmt; self.payload = payload; self.pairs = pairs

    def serialize(self, vals):
        if self.fmt == 'resident':
            header, blocks = self.payload
            out = list(header)
            for key, contents in blocks:
                out.append(key)
                for i, c in enumerate(contents):
                    v = vals.get('%s#%d' % (key, i), c)
                    out.append(v.replace('\r', ' ').replace('\n', ' '))   # mỗi đơn vị PHẢI đúng 1 dòng
            return '\n'.join(out) + '\n'
        out = []                                  # kv: giữ dòng #/không-phải-KEY=VALUE; thay value theo vals
        for ln in self.payload:
            if ln and not ln.lstrip().startswith('#') and '=' in ln:
                k = ln.split('=', 1)[0]
                if k in vals: out.append('%s=%s' % (k, vals[k])); continue
            out.append(ln)
        return '\n'.join(out) + '\n'

def _parse_resident(txt):
    txt = txt.lstrip('﻿')
    lines = txt.split('\n')
    if lines and lines[-1] == '': lines = lines[:-1]   # bỏ dòng rỗng cuối do '\n' kết file
    first = next((i for i, l in enumerate(lines) if RE_RKEY.match(l)), len(lines))
    header = lines[:first]
    blocks = []                                        # [(key, [content_lines])] — giữ NGUYÊN để serialize lại
    cur = None
    for l in lines[first:]:
        if RE_RKEY.match(l):
            cur = []; blocks.append((l, cur))
        else:
            if cur is None: cur = []; blocks.append(('', cur))   # phòng hờ (không xảy ra với file hợp lệ)
            cur.append(l)
    pairs = [('%s#%d' % (key, i), c) for key, contents in blocks for i, c in enumerate(contents)]
    return Doc('resident', (header, blocks), pairs)

def parse_doc(txt):
    """Đọc text -> Doc (tự nhận diện format). Lõi engine chỉ làm việc với Doc.pairs + Doc.serialize."""
    if detect_format(txt) == 'resident':
        return _parse_resident(txt)
    raw, pairs = parse_pairs_text(txt)
    return Doc('kv', raw, pairs)

def write_doc(path, doc, vals):
    """Ghi atomic (.tmp -> os.replace) theo đúng format của doc."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as w:
        w.write(doc.serialize(vals))
    os.replace(tmp, path)

def check_line(eng, vi):
    """Trả về list lý do lỗi (rỗng nếu OK)."""
    if not vi.strip(): return ['rỗng']
    r = []
    if '```' in vi: r.append('có_```')
    for nm, pat in (('{biến}', RE_CURLY), ('thẻ', RE_TAG), ('[..]', RE_REDACT)):
        if sorted(pat.findall(eng)) != sorted(pat.findall(vi)): r.append('lệch_' + nm)
    if eng.count('\\n') != vi.count('\\n'): r.append('lệch_\\n')
    if vi.strip() == eng.strip() and len(eng) > 30 and ' ' in eng.strip(): r.append('chưa_dịch?')
    return r

def make_batches(items, maxlines, maxchars):
    b, cur, ch = [], [], 0
    for it in items:
        n = len(it['en']) + 12
        if cur and (len(cur) >= maxlines or ch + n > maxchars): b.append(cur); cur, ch = [], 0
        cur.append(it); ch += n
    if cur: b.append(cur)
    return b

def build_user_prompt(items):
    payload = []
    for it in items:
        obj = {'id': it['id'], 'en': it['en']}
        ph = it.get('placeholders')
        if ph: obj['placeholders'] = ph
        payload.append(obj)
    return (
        "Dịch các mục sau sang tiếng Việt theo ĐÚNG quy tắc trong system prompt.\n"
        "- `placeholders` (nếu có) = token BẮT BUỘC giữ NGUYÊN, đúng vị trí trong `vi`.\n\n"
        + OUTPUT_REMINDER + "\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )

def parse_json_array(content):
    """Trích JSON array từ content model (bỏ ```json fences / text thừa)."""
    c = content.strip()
    if c.startswith('```'):
        c = c.split('\n', 1)[1] if '\n' in c else c
        c = c.rsplit('```', 1)[0]
    c = c.strip()
    i, j = c.find('['), c.rfind(']')
    if i != -1 and j != -1 and j > i: c = c[i:j + 1]
    return json.loads(c)

def load_keys_from(path, dead=None):
    out = []
    for ln in read_text(path).split('\n'):
        ln = ln.strip()
        if ln and not ln.startswith('#') and ln not in out: out.append(ln)
    return [k for k in out if not dead or k not in dead]

def sample_for_prompt(pairs, max_lines=120, max_chars=6000):
    """Lấy mẫu rải đều (đầu/giữa/cuối) từ các dòng cần dịch để gửi cho AI sinh prompt."""
    cand = [(k, v) for k, v in pairs if v.strip() and v != k]
    if not cand: return ''
    if len(cand) > max_lines:
        step = len(cand) / max_lines
        cand = [cand[int(i * step)] for i in range(max_lines)]
    out, ch = [], 0
    for k, v in cand:
        ln = '%s=%s' % (k, v)
        if ch + len(ln) > max_chars: break
        out.append(ln); ch += len(ln)
    return '\n'.join(out)

# ============================== PROVIDER (2 format API) ==============================
class RateLimit(Exception): pass
class DeadKey(Exception): pass
class Transient(Exception): pass

def _norm_base(base):
    """Chuẩn hóa base_url: bỏ '/' thừa và NÂNG http->https cho host công khai.
    (Server LLM ép https; gọi http -> 301 và httpx đổi POST thành GET -> hỏng.
     Giữ http cho localhost / LAN nội bộ để vẫn dùng được server dev.)"""
    base = (base or '').strip().rstrip('/')
    if base.startswith('http://'):
        host = base[len('http://'):].split('/')[0].split(':')[0].lower()
        local = (host in ('localhost', '127.0.0.1', '0.0.0.0', '::1')
                 or host.startswith('127.') or host.startswith('192.168.') or host.startswith('10.'))
        if not local:
            base = 'https://' + base[len('http://'):]
    return base

def _join_v1(base, suffix):
    """Ghép endpoint, tự bổ sung /v1. Người dùng chỉ cần điền domain (vd http://chat.trollllm.xyz);
    chấp nhận dư dấu '/' hoặc đã sẵn '/v1'. -> luôn ra <base>/v1<suffix>."""
    base = _norm_base(base)
    if base.endswith('/v1'):
        base = base[:-3].rstrip('/') + '/v1'   # gộp '/v1' (kể cả khi có '//v1')
    else:
        base = base + '/v1'
    return base + suffix

class Provider:
    """Base: giữ httpx client (pooling) + retry/map-lỗi CHUNG. Subclass override 4 hàm THUẦN."""
    name = 'base'
    def __init__(self, base_url, max_tokens=8192, temperature=0.3, timeout=180, max_conns=32):
        self.base_url = _norm_base(base_url)
        self.max_tokens = max_tokens; self.temperature = temperature; self.timeout = timeout
        self._limits = httpx.Limits(max_connections=max_conns, max_keepalive_connections=max_conns)
        self._client = None; self._client_lock = threading.Lock()

    # --- subclass override (PURE) ---
    def endpoint(self): raise NotImplementedError
    def headers(self, key): raise NotImplementedError
    def build_body(self, model, system, user): raise NotImplementedError
    def parse_content(self, j): raise NotImplementedError
    def list_models_endpoint(self): return None
    def parse_models(self, j): return []

    # --- httpx client dùng chung (lazy, thread-safe; tái dùng TLS connection) ---
    @property
    def client(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    kw = dict(limits=self._limits, timeout=httpx.Timeout(self.timeout),
                              follow_redirects=True)   # tự theo 301 (vd http -> https) cho GET
                    try:
                        self._client = httpx.Client(http2=True, **kw)
                    except Exception:   # thiếu gói h2 -> dùng HTTP/1.1 keep-alive (vẫn pooling)
                        self._client = httpx.Client(**kw)
        return self._client

    def close(self):
        c = self._client; self._client = None
        if c is not None:
            try: c.close()
            except Exception: pass

    # --- CHUNG: map lỗi theo status code ---
    def _raise_for_status(self, r):
        code = r.status_code
        if code < 400: return
        try: msg = r.text
        except Exception: msg = ''
        low = msg.lower()
        if code == 429 or 'rate' in low or 'quota' in low or 'resource_exhausted' in low:
            raise RateLimit(msg)
        if code in (401, 403):
            raise DeadKey(msg)
        if code in (500, 502, 503, 504, 408):
            raise Transient('HTTP %d' % code)
        raise Transient('HTTP %d: %s' % (code, msg[:120]))

    def _post(self, url, headers, body, timeout=None):
        try:
            r = self.client.post(url, headers={**headers, 'Content-Type': 'application/json'},
                                 json=body, timeout=timeout or self.timeout)
        except httpx.HTTPError as e:
            raise Transient(str(e)[:120])
        self._raise_for_status(r)
        try: return r.json()
        except Exception: raise Transient('no_json: ' + (r.text[:120] if hasattr(r, 'text') else ''))

    def call(self, model, key, system, user):
        j = self._post(self.endpoint(), self.headers(key), self.build_body(model, system, user))
        return self.parse_content(j)

    def list_models(self, key):
        url = self.list_models_endpoint()
        if not url: return []
        try:
            r = self.client.get(url, headers=self.headers(key), timeout=20)
            if r.status_code >= 400: return []
            return self.parse_models(r.json())
        except Exception:
            return []

class OpenAIProvider(Provider):
    name = 'openai'
    def endpoint(self): return _join_v1(self.base_url, '/chat/completions')
    def headers(self, key): return {'Authorization': 'Bearer ' + key}
    def build_body(self, model, system, user):
        return {'model': model,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}],
                'temperature': self.temperature, 'max_tokens': self.max_tokens}
    def parse_content(self, j):
        try: return j['choices'][0]['message']['content']
        except Exception: raise Transient('no_content: ' + json.dumps(j)[:150])
    def list_models_endpoint(self): return _join_v1(self.base_url, '/models')
    def parse_models(self, j):
        return sorted(m['id'] for m in j.get('data', []) if m.get('id'))

class AnthropicProvider(Provider):
    name = 'anthropic'
    def endpoint(self): return _join_v1(self.base_url, '/messages')
    def headers(self, key):
        return {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    def build_body(self, model, system, user):
        return {'model': model, 'max_tokens': self.max_tokens, 'system': system,
                'messages': [{'role': 'user', 'content': user}],
                'temperature': self.temperature}
    def parse_content(self, j):
        try:
            blocks = j['content']
            txt = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            return txt or blocks[0]['text']
        except Exception:
            raise Transient('no_content: ' + json.dumps(j)[:150])
    def list_models_endpoint(self): return None

def make_provider(cfg):
    cls = {'openai': OpenAIProvider, 'anthropic': AnthropicProvider}.get(cfg.get('provider', 'openai'), OpenAIProvider)
    max_conns = max(8, int(cfg.get('workers', 8)) + 4)   # pool đủ cho số luồng song song
    return cls(cfg.get('base_url', ''), cfg.get('max_tokens', 8192),
               cfg.get('temperature', 0.3), cfg.get('timeout', 180), max_conns)

# ============================== TIỆN ÍCH CẤP CAO ==============================
# (provider tạm dùng 1 lần -> đóng client httpx sau khi xong)
def list_models(provider, key):
    try: return provider.list_models(key)
    finally: provider.close()

def test_connection(provider, key, model):
    """Gửi 1 request nhỏ. Trả (ok: bool, msg: str)."""
    try:
        txt = provider.call(model, key, 'You are a test.', 'Reply with exactly: OK')
        return True, (txt or '').strip()[:80] or 'OK'
    except RateLimit as e:
        return False, 'Hết quota / rate-limit: %s' % str(e)[:100]
    except DeadKey as e:
        return False, 'API key không hợp lệ (401/403): %s' % str(e)[:100]
    except Transient as e:
        return False, 'Lỗi tạm thời (sẽ retry khi dịch): %s' % str(e)[:100]
    except Exception as e:
        return False, str(e)[:120]
    finally:
        provider.close()

def gen_system_prompt(provider, key, model, sample_text, game_name='', tone='', note='', timeout=180):
    """TỰ SINH system prompt dịch từ tên game + mẫu text game EN."""
    provider.timeout = timeout
    try:
        user = GEN_META_USER
        if game_name: user += '\nTÊN GAME: %s\n' % game_name
        if tone: user += 'TONE MONG MUỐN: %s\n' % tone
        if note: user += 'GHI CHÚ THÊM: %s\n' % note
        user += '\n===== MẪU TEXT GAME (EN) =====\n' + sample_text
        return provider.call(model, key, GEN_META_SYS, user).strip()
    finally:
        provider.close()

def build_system_prompt(cfg):
    """Ghép system prompt khi dịch: ưu tiên sysprompt (tự sinh/sửa tay), nếu rỗng -> luật mặc định."""
    sp = (cfg.get('sysprompt') or '').strip()
    if sp:
        parts = [sp]
    else:
        parts = [UNIVERSAL_RULES]
        if cfg.get('tone'): parts.append('=== VĂN PHONG / TONE ===\n' + cfg['tone'])
        if cfg.get('context'): parts.append('=== BỐI CẢNH & CỐT TRUYỆN ===\n' + cfg['context'])
        rules = read_text(cfg.get('prompt', '')).strip()
        if rules: parts.append('=== LUẬT DỊCH RIÊNG ===\n' + rules)
        gloss = read_text(cfg.get('glossary', '')).strip() if cfg.get('glossary') else ''
        if gloss: parts.append('=== GLOSSARY ===\n' + gloss)
    parts.append(OUTPUT_REMINDER)
    return '\n\n'.join(parts)

# ============================== CHECKPOINT / RESUME ==============================
def load_progress(pairs, eng_of, out_path):
    """Đọc mốc đã dịch từ file output + <out>.done.txt -> (vals, done).
    File OUTPUT là nguồn chân lý: chỉ coi 1 key là 'đã xong' khi output thật sự có dòng đó
    -> nếu xóa output mà còn done.txt thì vẫn dịch lại đúng (không bỏ sót)."""
    out_path = out_path or ''
    vals = {}
    if out_path and os.path.exists(out_path):
        vals = dict(parse_doc(read_text(out_path)).pairs)   # nguồn chân lý = output (đa-format)
    raw_done = set(x.strip() for x in read_text(out_path + '.done.txt').split('\n') if x.strip())
    done = {k for k in raw_done if k in vals}
    for k, v in vals.items():                      # tự dò dòng đã dịch sẵn trong output
        if k in eng_of and v.strip() and v != eng_of[k]: done.add(k)
    return vals, done

def resume_status(src, out):
    """Tiến độ đã lưu để UI hiển thị (KHÔNG sửa file). Trả {total, done, todo}
    tính theo SỐ DÒNG CẦN DỊCH (bỏ dòng rỗng / ID=ID)."""
    txt = read_text(src)
    if not txt: return {'total': 0, 'done': 0, 'todo': 0}
    pairs = parse_doc(txt).pairs
    eng_of = {k: v for k, v in pairs}
    _, done = load_progress(pairs, eng_of, out)
    translatable = [k for k, v in pairs if v.strip() and v != k]
    d = sum(1 for k in translatable if k in done)
    return {'total': len(translatable), 'done': d, 'todo': len(translatable) - d}

# status: 0 = ok/không cần dịch, 1 = chưa dịch, 2 = nghi lỗi placeholder
def build_preview_rows(src, out):
    """Đối chiếu key/EN/VI cho tab XEM TRƯỚC (hàm THUẦN, chạy được ở thread nền).
    Trả (rows, stats): rows = list (key, en, vi, status); stats theo dòng cần dịch."""
    txt = read_text(src)
    if not txt:
        return [], {'total': 0, 'done': 0, 'pending': 0, 'bad': 0}
    pairs = parse_doc(txt).pairs
    vmap = {}
    if out and os.path.exists(out):
        vmap = dict(parse_doc(read_text(out)).pairs)
    rows = []; done = pending = bad = 0
    for k, en in pairs:
        vi = vmap.get(k, '')
        if not en.strip() or en == k:
            status = 0
        elif not vi.strip() or vi == en:
            status = 1
        elif check_line(en, vi):
            status = 2
        else:
            status = 0
        rows.append((k, en, vi, status))
        if en.strip() and en != k:
            done += status == 0; pending += status == 1; bad += status == 2
    return rows, {'total': done + pending + bad, 'done': done, 'pending': pending, 'bad': bad}

# ============================== ORCHESTRATOR ĐA LUỒNG ==============================
class TranslationRun:
    """Điều phối dịch đa luồng. Phát sự kiện qua emit(evt: dict). stop = threading.Event."""
    def __init__(self, cfg, emit, stop):
        self.cfg = cfg; self.emit = emit; self.stop = stop
        self.provider = make_provider(cfg)
        self.sys_p = build_system_prompt(cfg)
        self.models = cfg.get('models') or [cfg.get('model', '')]
        self.models = [m for m in self.models if m]
        self.lock = threading.Lock()
        self.combo_ok = {}; self.dead = set(); self.rr = 0
        self.slot_map = {}; self.slot_next = 0
        self.stats = {'by_model': {}, 'ok': 0, 'err': 0, 'retries': 0}
        self.t0 = time.time(); self.done0 = 0
        self.total = 0; self.ndone = 0

    # ---- emit helpers ----
    def log(self, s): self.emit({'type': 'log', 'msg': s})

    def emit_progress(self):
        el = max(1e-6, time.time() - self.t0)
        rate = (self.ndone - self.done0) / el          # dòng/giây
        rem = (self.total - self.ndone) / rate if rate > 0 else 0
        pct = int(self.ndone * 100 / self.total) if self.total else 0
        self.emit({'type': 'progress', 'done': self.ndone, 'total': self.total, 'pct': pct,
                   'rate': rate, 'eta_sec': int(rem), 'elapsed': int(el)})

    def emit_stats(self):
        self.emit({'type': 'stats', **{k: (dict(v) if isinstance(v, dict) else v)
                                        for k, v in self.stats.items()}})

    def slot_of(self):
        tid = threading.get_ident()
        with self.lock:
            if tid not in self.slot_map:
                self.slot_map[tid] = self.slot_next; self.slot_next += 1
            return self.slot_map[tid]

    # ---- key/model rotation ----
    def _live_keys(self):
        src = self.cfg.get('keys') or []
        if isinstance(src, str):
            src = load_keys_from(src)
        return [k for k in src if k not in self.dead]

    def pick_combo(self):
        with self.lock:
            keys = self._live_keys()
            if not keys: return ('__NOKEY__', None)
            combos = [(m, k) for m in self.models for k in keys]
            now = time.time()
            ready = [c for c in combos if self.combo_ok.get(c, 0) <= now]
            if not ready:
                return ('__WAIT__', max(1, min(self.combo_ok[c] for c in combos) - now))
            c = ready[self.rr % len(ready)]; self.rr += 1
            return c

    def translate_batch(self, items, label, batch_id, slot):
        """Dịch 1 lô -> dict {id: vi}. Tự retry + xoay model/key."""
        user_text = build_user_prompt(items)
        retry = 0
        while not self.stop.is_set():
            mdl, key = self.pick_combo()
            if mdl == '__NOKEY__':
                self.log('   !! Chưa có API key — thêm key rồi chờ 15s'); time.sleep(15); continue
            if mdl == '__WAIT__':
                self.emit({'type': 'worker', 'slot': slot, 'batch_id': batch_id,
                           'model': '', 'status': 'waiting'})
                time.sleep(min(key, 8)); continue
            self.emit({'type': 'worker', 'slot': slot, 'batch_id': batch_id,
                       'model': mdl, 'status': 'translating'})
            try:
                content = self.provider.call(mdl, key, self.sys_p, user_text)
                results = parse_json_array(content)
                out = {}
                for r in results:
                    if isinstance(r, dict) and 'id' in r and 'vi' in r:
                        out[r['id']] = str(r['vi'])
                miss = [it['id'] for it in items if it['id'] not in out]
                if len(miss) > len(items) * 0.25 and retry < self.cfg.get('retries', 5):
                    retry += 1
                    with self.lock: self.stats['retries'] += 1
                    self.log('   [%s] thiếu %d mục -> thử lại' % (label, len(miss))); continue
                with self.lock:
                    self.stats['ok'] += 1
                    self.stats['by_model'][mdl] = self.stats['by_model'].get(mdl, 0) + 1
                return out
            except RateLimit:
                with self.lock: self.combo_ok[(mdl, key)] = time.time() + 60
                self.emit({'type': 'batch', 'batch_id': batch_id, 'state': 'retry',
                           'model': mdl, 'err': 'rate-limit', 'label': label})
                self.log('   [%s] %s hết quota -> đổi model/key' % (label, mdl)); continue
            except DeadKey:
                with self.lock: self.dead.add(key)
                self.log('   [%s] key %s.. không hợp lệ -> bỏ' % (label, str(key)[:12])); continue
            except (Transient, json.JSONDecodeError, ValueError) as e:
                with self.lock:
                    self.combo_ok[(mdl, key)] = time.time() + 8
                    self.stats['retries'] += 1
                retry += 1
                self.emit({'type': 'batch', 'batch_id': batch_id, 'state': 'retry',
                           'model': mdl, 'err': str(e)[:60], 'label': label})
                self.log('   [%s] lỗi %s (thử %d) -> đổi/đợi' % (label, str(e)[:60], retry))
                if retry > self.cfg.get('retries', 5) + 4:
                    with self.lock: self.stats['err'] += 1
                    return {}
                time.sleep(min(2 * retry, 10)); continue
        return {}

    def run(self):
        cfg = self.cfg
        src_txt = read_text(cfg['src'])
        if not src_txt:
            self.emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0,
                       'msg': 'Không đọc được file đầu vào.'}); return
        doc = parse_doc(src_txt)                  # tự nhận diện KEY=VALUE hoặc Resident $KEY-block
        pairs = doc.pairs
        eng_of = {k: v for k, v in pairs}
        out_path = cfg['out']; donef_path = out_path + '.done.txt'
        vals, done = load_progress(pairs, eng_of, out_path)   # mốc đã dịch (resume)
        todo = [(k, v) for k, v in pairs if k not in done and v.strip() and v != k]
        self.total = len(pairs); self.ndone = len(done); self.done0 = len(done)
        self.emit_progress()
        if done:
            self.log('Resume: đã có %d dòng dịch trước đó -> chỉ dịch %d dòng còn lại.' % (len(done), len(todo)))
        self.log('=== BẮT ĐẦU === tổng %d | đã xong %d | còn %d | %d luồng | model: %s'
                 % (self.total, len(done), len(todo), cfg.get('workers', 8), ', '.join(self.models)))
        donef = open(donef_path, 'a', encoding='utf-8')

        def run_parallel(work_pairs, label):
            id_to_key = {}; items = []
            for i, (k, en) in enumerate(work_pairs):
                id_to_key[i] = k
                items.append({'id': i, 'en': en, 'placeholders': extract_placeholders(en)})
            batches = make_batches(items, cfg.get('maxlines', 50), cfg.get('maxchars', 8000))
            self.emit({'type': 'batch_init', 'n_batches': len(batches), 'label': label})
            self.log('  %s: %d dòng -> %d lô (chạy %d luồng)'
                     % (label, len(items), len(batches), cfg.get('workers', 8)))

            def handle(args):
                bi, batch = args
                if self.stop.is_set(): return
                slot = self.slot_of()
                self.emit({'type': 'batch', 'batch_id': bi, 'state': 'running',
                           'n_lines': len(batch), 'label': label})
                got = self.translate_batch(batch, '%s %d/%d' % (label, bi + 1, len(batches)), bi, slot)
                if self.stop.is_set(): return
                with self.lock:
                    for it in batch:
                        k = id_to_key[it['id']]
                        vi = got.get(it['id'])
                        vals[k] = vi if (vi and vi.strip()) else eng_of[k]
                        if k not in done: done.add(k); donef.write(k + '\n')
                    donef.flush(); write_doc(out_path, doc, vals)
                    self.ndone = len(done)
                self.emit({'type': 'batch', 'batch_id': bi,
                           'state': 'done' if got else 'error', 'label': label})
                self.emit({'type': 'worker', 'slot': slot, 'batch_id': None,
                           'model': '', 'status': 'idle'})
                self.emit_progress(); self.emit_stats()

            with ThreadPoolExecutor(max_workers=cfg.get('workers', 8)) as ex:
                list(ex.map(handle, list(enumerate(batches))))
            return not self.stop.is_set()

        if todo and not run_parallel(todo, 'Dịch'):
            donef.close()
            self.emit({'type': 'finished', 'status': 'stopped', 'total': self.total,
                       'done': len(done), 'bad': 0, 'msg': 'Đã dừng (resume sau).'}); return

        for rnd in range(1, cfg.get('rounds', 6) + 1):
            if self.stop.is_set(): break
            bad = [k for k, _ in pairs if k in vals and eng_of[k].strip()
                   and eng_of[k] != k and check_line(eng_of[k], vals[k])]
            if not bad:
                donef.close()
                self.emit({'type': 'finished', 'status': 'ok', 'total': self.total,
                           'done': self.total, 'bad': 0,
                           'msg': 'HOÀN TẤT - SẠCH LỖI! (%d dòng)' % self.total})
                return
            self.log('--- Vòng kiểm %d: %d dòng lỗi -> dịch lại ---' % (rnd, len(bad)))
            with self.lock:
                for k in bad: done.discard(k)
            self.ndone = len(done)
            if not run_parallel([(k, eng_of[k]) for k in bad], 'Sửa-v%d' % rnd):
                donef.close()
                self.emit({'type': 'finished', 'status': 'stopped', 'total': self.total,
                           'done': len(done), 'bad': len(bad), 'msg': 'Đã dừng (resume sau).'}); return
        donef.close()
        bad = [k for k, _ in pairs if k in vals and eng_of[k].strip()
               and eng_of[k] != k and check_line(eng_of[k], vals[k])]
        self.emit({'type': 'finished', 'status': 'ok', 'total': self.total, 'done': len(done),
                   'bad': len(bad), 'msg': 'Xong (còn %d dòng nghi lỗi - bấm Bắt đầu lại để sửa).' % len(bad)})

def run_translation(cfg, emit, stop):
    """Điểm vào engine. Chạy blocking (gọi bên trong QThread ở app.py)."""
    run = None
    try:
        run = TranslationRun(cfg, emit, stop)
        run.run()
    except Exception as e:
        import traceback
        emit({'type': 'log', 'msg': '!! LỖI: %s\n%s' % (e, traceback.format_exc()[:600])})
        emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0, 'msg': str(e)[:120]})
    finally:
        if run is not None:
            try: run.provider.close()      # đóng connection pool httpx
            except Exception: pass
