import codecs
import hashlib
import json
import random
import re
import socket
import sublime
import sublime_plugin
import threading
import time
import types
import urllib

SETTINGS_FILE = 'Inspr.sublime-settings'

MAXIMUM_QUERY_CHARS = 64
MAXIMUM_CACHE_WORDS = 32768

# Error Code
OK              = 0
EMPTY_RESPONSE  = 1
NETWORK_TIMEOUT = 2

ERROR_MSG = {
    OK:              '',
    EMPTY_RESPONSE:  '无结果，换个关键字吧',
    NETWORK_TIMEOUT: '连接超时，请检查网络与配置',
    20:              '要翻译的文本过长',
    30:              '有道：无法进行有效的翻译',
    40:              '有道：不支持的语言类型',
    50:              '有道：无效的 key',
    60:              '有道：无词典结果，仅在获取词典结果生效',
    52001:           '百度：请求超时，请检查网络与配置',
    52002:           '百度：系统错误，请重试',
    52003:           '百度：未授权用户，请检查 appid 是否正确',
    54000:           '百度：必填参数为空，请检查是否少传参数',
    58000:           '百度：客户端 IP 非法',
    54001:           '百度：签名错误，请请检查签名生成方法',
    54003:           '百度：访问频率受限，请降低调用频率',
    58001:           '百度：译文语言方向不支持',
    54004:           '百度：账户余额不足',
    54005:           '百度：长 query 请求频繁，请降低长 query 的发送频率',
    999:             '微软：Access Token 错误'
}

# Case styles
LOWER_CAMEL_CASE  = 'lower_camel_case'
UPPER_CAMEL_CASE  = 'upper_camel_case'
LOWER_UNDERSCORES = 'lower_underscores'
UPPER_UNDERSCORES = 'upper_underscores'

# Settings
DICTIONARY_SOURCE        = 'dictionary_source'
CLEAR_SELECTION          = 'clear_selection'
AUTO_DETECT_WORDS        = 'auto_detect_words'
IGNORE_WORDS             = 'ignore_words'
FULL_INSPIRATION         = 'full_inspiration'
SHOW_WITH_MONOSPACE_FONT = 'show_with_monospace_font'
HTTP_PROXY               = 'http_proxy'

# Default Settings Value
DEFAULT_DIC_SROUCE               = ['Baidu']
DEFAULT_CLEAR_SELECTION          = True
DEFAULT_AUTO_DETECT_WORDS        = True
DEFAULT_IGNORE_WORDS             = ["A", "a", "the", "The"]
DEFAULT_FULL_INSPIRATION         = False
DEFAULT_SHOW_WITH_MONOSPACE_FONT = True
DEFAULT_HTTP_PROXY               = ''

DICTIONARY_CACHE = {}
clear_global_cache = DICTIONARY_CACHE.clear

def get_settings(name, default=None):
    settings = sublime.load_settings(SETTINGS_FILE)
    v = settings.get(name)
    if v == None:
        try:
            return sublime.active_window().active_view().settings().get(name, default)
        except AttributeError:
            return default
    else:
        return v

def to_lower_camel_case(string):
    s = to_upper_camel_case(string)
    return ''.join(word[0].lower() + word[1:] for word in s.split())

def to_upper_camel_case(string):
    return ''.join(a for a in string.title() if not a.isspace())

def to_lower_underscores(string):
    return re.sub('[ \']', '_', string).lower()

def to_upper_underscores(string):
    a = to_lower_underscores(string)
    return a.upper()

def ignore_and_filter(string, skip):
    tokens = string.split()
    result = []
    for token in tokens:
        if token not in skip:
            result.append(token)
    return ' '.join(result)

def get_corresponding_style_function(case_style):
    mapper = style_functions
    return mapper[case_style] if case_style in mapper else to_lower_camel_case

def get_json(url, args, method):
    error_code, result = get_response(url, args, method)
    json_result = {}
    try:
        json_result = json.loads(result)
    except:
        print('JSON parse error: %s' % result)
    return error_code, json_result

def get_response(url, args, method):

    req = urllib.request

    if method != 'GET' and method != 'POST':
        return ''

    proxy = get_settings(HTTP_PROXY, DEFAULT_HTTP_PROXY)

    opener = None
    if proxy != '' and proxy != None:
        proxy_opener = req.ProxyHandler({'http': proxy})
        opener = req.build_opener(proxy_opener)

    resp = None
    timeout = 10

    try:
        if method == 'GET':
            url = url + urllib.parse.urlencode(args)
            resp = req.urlopen(url, timeout=timeout) if opener == None else opener.open(url, timeout=timeout)
        else:
            postdata = urllib.parse.urlencode(args)
            postdata = postdata.encode('utf-8')
            _req = req.Request(url=url, data=postdata)
            resp = req.urlopen(_req, timeout=timeout) if opener == None else opener.open(_req, timeout=timeout)
    except urllib.error.URLError as e:
        print(e)
        return OK, ''
    except socket.timeout as e:
        return NETWORK_TIMEOUT, ''

    data     = resp.read()
    encoding = resp.info().get_content_charset('utf-8')

    resp.close()

    return OK, data.decode(encoding)

class InsprCommand(sublime_plugin.TextCommand):

    def run(self, edit, **args):
        InsprQueryThread(edit, self.view, **args).start()

class InsprQueryThread(threading.Thread):

    def __init__(self, edit, view, **args):
        self.edit         = edit
        self.view         = view
        self.window       = view.window()
        self.translations = []
        self.args         = args
        threading.Thread.__init__(self)

    def run(self):

        cache = DICTIONARY_CACHE
        case_style     = self.args['case_style'] if 'case_style' in self.args else LOWER_CAMEL_CASE
        style_function = get_corresponding_style_function(case_style)

        sel = self.view.sel()[0]
        if sel.begin() == sel.end() and get_settings(AUTO_DETECT_WORDS, DEFAULT_AUTO_DETECT_WORDS):
            self.view.run_command("inspr_auto_detect_words")

        word = self.view.substr(self.view.sel()[0]).strip()
        if len(word) == 0 or word.isspace():
            return

        self.window.status_message('Search for: ' + word + '...')

        # if cache hit
        if self.is_cache_hit(cache, word, case_style):
            self.translations.extend(cache[word][case_style])
            self.window.show_quick_panel(self.translations, self.on_done)
            return

        # select source
        cause = 0
        causes = []
        candidates = []
        dic_source = get_settings(DICTIONARY_SOURCE, DEFAULT_DIC_SROUCE)

        if dic_source == None:
            dic_source = DEFAULT_DIC_SROUCE

        for dic in dic_source:
            if dic in translator_map:
                (c, candidate) = translator_map[dic].translate(word)
                causes.append(c)
                candidates.extend(candidate)

        if OK not in causes:
            cause = causes[0]

        ignore = get_settings(IGNORE_WORDS, DEFAULT_IGNORE_WORDS)

        for trans in candidates:
            # split by space and skip words
            if ignore:
                trans = ignore_and_filter(trans, ignore)
            case = style_function(trans)
            self.translations.append(case)

        def isidentifier(string):
            return re.match('[0-9a-zA-Z_]+', string) != None

        for idx, val in enumerate(self.translations):
            self.translations[idx] = re.sub('[-.:\'/,]', '', val)
        self.translations = sorted(filter(isidentifier, set(self.translations)))

        if self.translations and cause == OK:
            self.cache_words(cache, word, case_style)
            if get_settings(SHOW_WITH_MONOSPACE_FONT, DEFAULT_SHOW_WITH_MONOSPACE_FONT):
                self.window.show_quick_panel(self.translations, self.on_done, sublime.MONOSPACE_FONT)
            else:
                self.window.show_quick_panel(self.translations, self.on_done)
        elif len(self.translations) == 0:
            self.view.show_popup(ERROR_MSG[EMPTY_RESPONSE])
        else:
            self.view.show_popup(ERROR_MSG[int(cause)])

    def cache_words(self, cache, word, case_style):

        if len(cache.keys()) > MAXIMUM_CACHE_WORDS:
            clear_global_cache()

        if word not in cache:
            cache[word] = {}

        if case_style not in cache[word]:
            cache[word][case_style] = []

        cache[word][case_style] = self.translations

    def is_cache_hit(self, cache, word, case_style):
        return word in cache and case_style in cache[word]

    def on_done(self, picked):

        if picked == -1:
            return

        trans = self.translations[picked]
        args = { 'text': trans }

        def replace_selection():
            self.view.run_command("inspr_replace_selection", args)

        sublime.set_timeout(replace_selection, 10)

class InsprReplaceSelectionCommand(sublime_plugin.TextCommand):

    def run(self, edit, **replacement):

        if 'text' not in replacement:
            return

        view = self.view
        selection = view.sel()
        translation = replacement['text']

        view.replace(edit, selection[0], translation)

        clear_sel = get_settings(CLEAR_SELECTION, DEFAULT_CLEAR_SELECTION)
        if not clear_sel:
            return

        pt = selection[0].end()

        selection.clear()
        selection.add(sublime.Region(pt))

        view.show(pt)

class InsprAutoDetectWordsCommand(sublime_plugin.TextCommand):

    def run(self, edit):

        view = self.view
        sel  = view.sel()[0]

        if (sel.begin() != sel.end()):
            return

        pt = sel.begin()
        clsfy = view.classify(pt)

        # sublime.CLASS_WORD_START
        # sublime.CLASS_WORD_END
        # sublime.CLASS_PUNCTUATION_START
        # sublime.CLASS_PUNCTUATION_END
        # sublime.CLASS_SUB_WORD_START
        # sublime.CLASS_SUB_WORD_END
        # sublime.CLASS_LINE_START
        # sublime.CLASS_LINE_END
        # sublime.CLASS_EMPTY_LINE

        flag = 0
        offset = 0

        if clsfy & sublime.CLASS_WORD_START != 0:
            # go right until word end or line end
            flag = (sublime.CLASS_WORD_END | sublime.CLASS_SUB_WORD_END | sublime.CLASS_LINE_END)
            offset = 1
        elif clsfy & sublime.CLASS_WORD_END != 0:
            # go left until word start or line start
            flag = (sublime.CLASS_WORD_START | sublime.CLASS_SUB_WORD_START | sublime.CLASS_LINE_START)
            offset = -1
        else:
            return

        _pt    = pt
        _clsfy = clsfy
        begin, end = view.rowcol(pt)

        sentinel = 0
        while _clsfy & flag == 0:
            if sentinel > 32:
                return
            _pt = self.move_cursor_horizontally(_pt, offset)
            _clsfy = view.classify(_pt)
            _, end = view.rowcol(_pt)
            sentinel += 1

        view.sel().clear()
        view.sel().add(sublime.Region(pt, view.text_point(begin, end)))

    def move_cursor_horizontally(self, pt, offset):
        row, col = self.view.rowcol(pt)
        return self.view.text_point(row, col + offset)

class MicrosoftTranslator():

    def __init__(self):
        self.token_last_aquired = 0
        self.token_expires_in = 0
        self.token = ''
        MicrosoftTranslatorGetTokenThread(self).start()

    def translate(self, query):

        candidates = []

        error_code = self.get_latest_token()
        if error_code != OK:
            return (error_code, candidates)

        # https://github.com/MicrosoftTranslator/PythonConsole/blob/master/MTPythonSampleCode/MTPythonSampleCode.py
        if self.token == None or self.token == '':
            return (999, candidates)

        from_lang   = 'zh-CHS'
        to_lang     = 'en'

        # Call Microsoft Translator service
        headers = {
            'appId': self.token,
            'text': query,
            'to': to_lang
        }

        # <string xmlns="http://schemas.microsoft.com/2003/10/Serialization/">%s</string>
        error_code, translation = get_response(self.URL, headers, 'GET')
        if error_code != OK:
            return (error_code, candidates)

        candidates.extend(re.findall(r"<string.*>(.*)</string>", translation))

        return (OK, candidates)



class MicrosoftTranslatorGetTokenThread(threading.Thread):

    def __init__(self, translator):
        self.translator = translator
        threading.Thread.__init__(self)

    def run(self):
        self.translator.get_latest_token()

class TranslatorThread(threading.Thread):

    def __init__(self, query, full_inspiration=True, proxy=''):
        self.query = query
        self.full_inspiration = full_inspiration
        self.proxy = proxy
        self.status = OK
        self.translations = []
        threading.Thread.__init__(self)

    def run():
        self.status, self.translations = self.translate()

    def translate(self):
        # Query by given text and return result as a list
        return []

    def get_http_response(self, url, args, method='GET', timeout=10, proxy=''):

        req    = urllib.request
        opener = None

        if not proxy:
            proxy_opener = req.ProxyHandler({'http': proxy})
            opener = req.build_opener(proxy_opener)

        resp = None
        open_fuc = req.urlopen if opener == None else opener.open

        try:
            if method == 'GET':
                url += urllib.parse.urlencode(args)
                resp = opener_func(url, timeout=timeout)
            else:
                postdata = urllib.parse.urlencode(args).encode('utf-8')
                resp = opener_func(req.Request(url=url, data=postdata), timeout=timeout)
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.timeout):
                return NETWORK_TIMEOUT, ''
            else:
                # Raise the original error
                print(e)
                raise

        encoding = resp.info().get_content_charset('utf-8')
        resp.close()

        return OK, resp.read().decode(encoding)

    def get_json(url, args, method='GET', timeout=10, proxy=''):
        error_code, result = self.get_http_response(url, args, method, timeout, proxy)
        json_result = {}
        try:
            json_result = json.loads(result)
        except:
            print('JSON parse error: %s' % result)
        return error_code, json_result

    def get_translations():
        return self.status, self.translations

class YoudaoTranslatorThread(TranslatorThread):

    KEY      = '672847864'
    KEY_FROM = 'InsprMe'
    URL      = 'http://fanyi.youdao.com/openapi.do?'
    ARGS     = {
        'key':     KEY,
        'keyfrom': KEY_FROM,
        'type':    'data',
        'doctype': 'json',
        'version': '1.1',
        'q':       ''
    }

    def __init__(self, query, full_inspiration=True, proxy=''):
        TranslatorThread.__init__(self)

    def translate(self):

        self.ARGS['q'] = self.query.encode('utf-8')

        result = {}
        candidates = []

        error_code, result = self.get_json(self.URL, self.ARGS, proxy=self.proxy)
        if error_code != OK:
            return (error_code, candidates)

        if 'errorCode' in result:
            if result['errorCode'] != 0:
                return (result['errorCode'], candidates)
        if 'translation' in result:
            for trans in result['translation']:
                candidates.append(trans)
        if 'web' in result:
            for web in result['web']:
                strictly_matched = query == web['key']
                if self.full_inspiration or strictly_matched:
                    for trans in web['value']:
                        candidates.append(trans)

        return (OK, candidates)

class BaiduTranslatorThread(TranslatorThread):

    APP_ID     = '20161205000033482'
    SECRET_KEY = 'bFPDI4jI5jI61S7VpyLR'
    URL        = 'http://api.fanyi.baidu.com/api/trans/vip/translate?'
    ARGS       = {
        'appid': APP_ID,
        'from':  'zh',
        'to':    'en',
        'salt':  '',
        'sign':  '',
        'q':     ''
    }

    def __init__(self, query, full_inspiration=True, proxy=''):
        TranslatorThread.__init__(self)

    def translate(self):

        salt = self.rand()

        self.ARGS['salt'] = salt
        self.ARGS['sign'] = self.get_sign(salt)
        self.ARGS['q']    = self.query

        result = {}
        candidates = []

        error_code, result = get_json(self.URL, self.ARGS, proxy=self.proxy)
        if error_code != OK:
            return (error_code, candidates)

        if 'error_code' in result:
            return (result['error_code'], candidates)

        if 'trans_result' in result:
            for trans in result['trans_result']:
                candidates.append(trans['dst'])

        return (OK, candidates)

    def rand(self):
        return random.randint(32768, 65536)

    def get_sign(self, salt):
        sign = self.APP_ID + self.query + str(salt) + self.SECRET_KEY
        md5  = hashlib.md5()
        md5.update(sign.encode('utf-8'))
        sign = md5.hexdigest()
        return sign

MT_TOKEN_LAST_ACCQUIRED = 0
MT_TOKEN_EXPIRES_IN = 0
MT_TOKEN_CACHE = ''

class MicrosoftTranslatorThread(TranslatorThread):

    CLIENT_ID     = 'inspr'
    CLIENT_SECRET = 'awhg2KcdFKnwhylSNYeZIrKGhdIGv2g63YrSjOSo'
    SCOPE         = 'http://api.microsofttranslator.com'
    GRANT_TYPE    = 'client_credentials'
    OAUTH_URL     = 'https://datamarket.accesscontrol.windows.net/v2/OAuth2-13'
    URL           = 'http://api.microsofttranslator.com/v2/Http.svc/Translate?'
    ARGS = {
        'client_id':     CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope':         SCOPE,
        'grant_type':    GRANT_TYPE
    }

    def __init__(self, query, full_inspiration=True, proxy=''):
        TranslatorThread.__init__(self)

    def translate(self):

        candidates = []

        error_code = self.get_latest_token()
        if error_code != OK:
            return (error_code, candidates)

        # https://github.com/MicrosoftTranslator/PythonConsole/blob/master/MTPythonSampleCode/MTPythonSampleCode.py
        if self.token == None or self.token == '':
            return (999, candidates)

        from_lang   = 'zh-CHS'
        to_lang     = 'en'

        # Call Microsoft Translator service
        headers = {
            'appId': self.token,
            'text': query,
            'to': to_lang
        }

        # <string xmlns="http://schemas.microsoft.com/2003/10/Serialization/">%s</string>
        error_code, translation = get_response(self.URL, headers, 'GET')
        if error_code != OK:
            return (error_code, candidates)

        candidates.extend(re.findall(r"<string.*>(.*)</string>", translation))

        return (OK, candidates)

    def get_latest_token(self):

        if not self.is_access_token_expired():
            return OK

        error_code, oauth_token = get_json(self.OAUTH_URL, self.ARGS, 'POST')
        if error_code != OK:
            return error_code

        self.token              = 'Bearer %s' % oauth_token['access_token'] if 'access_token' in oauth_token else ''
        self.token_expires_in   = int(oauth_token['expires_in']) if 'expires_in' in oauth_token else 0
        self.token_last_aquired = int(time.time()) if self.token != '' else 0

        return OK

    def is_access_token_expired(self):
        return self.token == '' \
            or self.token_last_aquired + self.token_expires_in < int(time.time())

# Youdao source
youdao_client = YoudaoTranslator()

# Baidu source
baidu_client  = BaiduTranslator()

# Microsoft source
microsoft_client = MicrosoftTranslator()

# Style fuction map
style_functions = {
    LOWER_CAMEL_CASE:  to_lower_camel_case,
    UPPER_CAMEL_CASE:  to_upper_camel_case,
    LOWER_UNDERSCORES: to_lower_underscores,
    UPPER_UNDERSCORES: to_upper_underscores
}

# Translator client map
translator_map = {
    'Youdao': youdao_client,
    'Baidu':  baidu_client,
    'Microsoft': microsoft_client
}
