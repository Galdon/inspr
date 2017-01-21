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

# Settings file for Inspr
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
DICTIONARY_SOURCE           = 'dictionary_source'
CLEAR_SELECTION             = 'clear_selection'
AUTO_DETECT_WORDS           = 'auto_detect_words'
IGNORE_WORDS                = 'ignore_words'
FULL_INSPIRATION            = 'full_inspiration'
SHOW_WITH_MONOSPACE_FONT    = 'show_with_monospace_font'
HTTP_PROXY                  = 'http_proxy'
YOUDAO_KEY                  = 'youdao_key'
YOUDAO_KEY_FROM             = 'youdao_key_from'
BAIDU_APPID                 = 'baidu_appid'
BAIDU_SECRET_KEY            = 'baidu_secret_key'
MICROSOFT_CLIENT_ID         = 'microsoft_client_id'
MICROSOFT_CLIENT_SECRET_KEY = 'microsot_client_secret_key'

# Default Settings Value
DEFAULT_DIC_SROUCE                  = ['Baidu']
DEFAULT_CLEAR_SELECTION             = True
DEFAULT_AUTO_DETECT_WORDS           = True
DEFAULT_IGNORE_WORDS                = ["A", "a", "the", "The"]
DEFAULT_FULL_INSPIRATION            = False
DEFAULT_SHOW_WITH_MONOSPACE_FONT    = True
DEFAULT_HTTP_PROXY                  = ''
DEFAULT_YOUDAO_KEY                  = '672847864'
DEFAULT_YOUDAO_KEY_FROM             = 'InsprMe'
DEFAULT_BAIDU_APPID                 = '20161205000033482'
DEFAULT_BAIDU_SECRET_KEY            = 'bFPDI4jI5jI61S7VpyLR'
DEFAULT_MICROSOFT_CLIENT_ID         = 'inspr'
DEFAULT_MICROSOFT_CLIENT_SECRET_KEY = 'awhg2KcdFKnwhylSNYeZIrKGhdIGv2g63YrSjOSo'

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

def filter_ignored(string, skip):
    tokens = string.split()
    result = []
    for token in tokens:
        if token not in skip:
            result.append(token)
    return ' '.join(result)

def get_corresponding_style_function(case_style):
    mapper = style_functions
    return mapper[case_style] if case_style in mapper else to_lower_camel_case

class InsprCommand(sublime_plugin.TextCommand):

    translations = []
    args = None

    def run(self, edit, **args):
        self.translations.clear()
        self.args = args
        sublime.set_timeout_async(self.query, 0)

    def query(self):

        translations = self.translations
        window = self.view.window()

        cache = DICTIONARY_CACHE
        case_style     = self.args['case_style'] if 'case_style' in self.args else LOWER_CAMEL_CASE
        style_function = get_corresponding_style_function(case_style)

        sel = self.view.sel()[0]
        if sel.begin() == sel.end() and get_settings(AUTO_DETECT_WORDS, DEFAULT_AUTO_DETECT_WORDS):
            self.view.run_command("inspr_auto_detect_words")

        word = self.view.substr(self.view.sel()[0]).strip()
        if len(word) == 0 or word.isspace():
            return

        window.status_message('Search for: %s ...' % word)

        # if cache hit
        if self.is_cache_hit(cache, word, case_style):
            translations.extend(cache[word][case_style])
            self.show_translations(translations)
            return

        # select source
        cause = 0
        causes = []
        candidates = []
        dic_source = get_settings(DICTIONARY_SOURCE, DEFAULT_DIC_SROUCE)

        if dic_source == None:
            dic_source = DEFAULT_DIC_SROUCE

        pool = self.start_translate_and_join(dic_source, word)
        for thread in pool:
            thread.join()
        for thread in pool:
            (c, candidate) = thread.get_translations()
            causes.append(c)
            candidates.extend(candidate)

        if OK not in causes:
            cause = causes[0]

        ignore = get_settings(IGNORE_WORDS, DEFAULT_IGNORE_WORDS)

        for trans in candidates:
            # split by space and skip words
            if ignore:
                trans = re.sub('[&]', 'and', trans)
                trans = filter_ignored(trans, ignore)
            case = style_function(trans)
            translations.append(case)

        def isidentifier(string):
            return re.match('[0-9a-zA-Z_]+', string) != None

        for idx, val in enumerate(translations):
            translations[idx] = re.sub('[-.:\'!?/,]', '', val)
        self.translations = translations = sorted(filter(isidentifier, set(translations)))

        if translations and cause == OK:
            self.cache_words(cache, word, case_style)
            self.show_translations(translations)
            window.status_message('Search for: %s ... Done' % word)
        elif len(translations) == 0:
            self.view.show_popup(ERROR_MSG[EMPTY_RESPONSE])
        else:
            self.view.show_popup(ERROR_MSG[int(cause)])

    def show_translations(self, translations):
        window = self.view.window()
        if get_settings(SHOW_WITH_MONOSPACE_FONT, DEFAULT_SHOW_WITH_MONOSPACE_FONT):
            window.show_quick_panel(translations, self.on_done, sublime.MONOSPACE_FONT)
        else:
            window.show_quick_panel(translations, self.on_done)

    def start_translate_and_join(self, dic_source, word):
        full_inspiration = get_settings(FULL_INSPIRATION, DEFAULT_FULL_INSPIRATION)
        proxy = get_settings(HTTP_PROXY, DEFAULT_HTTP_PROXY)
        pool = []
        for dic in dic_source:
            create_thread = None
            if dic == 'Youdao':
                key = get_settings(YOUDAO_KEY, DEFAULT_YOUDAO_KEY)
                key_from = get_settings(YOUDAO_KEY_FROM, DEFAULT_YOUDAO_KEY_FROM)
                YoudaoTranslatorThread.KEY = key if key else DEFAULT_YOUDAO_KEY
                YoudaoTranslatorThread.KEY_FROM = key_from if key_from else DEFAULT_YOUDAO_KEY_FROM
                create_thread = YoudaoTranslatorThread
            elif dic == 'Baidu':
                app_id = get_settings(BAIDU_APPID, DEFAULT_BAIDU_APPID)
                secret_key = get_settings(BAIDU_SECRET_KEY, DEFAULT_BAIDU_SECRET_KEY)
                BaiduTranslatorThread.APP_ID = app_id if app_id else DEFAULT_BAIDU_APPID
                BaiduTranslatorThread.SECRET_KEY = secret_key if secret_key else DEFAULT_BAIDU_SECRET_KEY
                create_thread = BaiduTranslatorThread
            elif dic == 'Microsoft':
                create_thread = MicrosoftTranslatorThread
            if create_thread:
                thread = create_thread(word, full_inspiration = full_inspiration, proxy = proxy)
                pool.append(thread)
                thread.start()
        return pool

    def cache_words(self, cache, word, case_style):

        if len(cache.keys()) > MAXIMUM_CACHE_WORDS:
            clear_global_cache()

        if word not in cache:
            cache[word] = {}

        if case_style not in cache[word]:
            cache[word][case_style] = []

        cache[word][case_style] = list(self.translations)

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
            # Go right until word end or line end
            flag = (sublime.CLASS_WORD_END | sublime.CLASS_SUB_WORD_END | sublime.CLASS_LINE_END)
            offset = 1
        elif clsfy & sublime.CLASS_WORD_END != 0:
            # Go left until word start or line start
            flag = (sublime.CLASS_WORD_START | sublime.CLASS_SUB_WORD_START | sublime.CLASS_LINE_START)
            offset = -1
        else:
            return

        _pt    = pt
        _clsfy = clsfy
        begin, end = view.rowcol(pt)

        sentinel = 0
        while _clsfy & flag == 0:
            # In case of infinity loop
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

class TranslatorThread(threading.Thread):

    def __init__(self, query, full_inspiration=True, proxy=''):
        self.query = query
        self.full_inspiration = full_inspiration
        self.proxy = proxy
        self.status = OK
        self.translations = []
        threading.Thread.__init__(self)

    def run(self):
        self.status, self.translations = self.translate()

    def translate(self):
        # Query by given text and return result as a list
        return []

    @staticmethod
    def get_http_response(url, args, method='GET', timeout=8, proxy=''):

        req    = urllib.request
        opener = None

        if proxy:
            proxy_opener = req.ProxyHandler({'http': proxy})
            opener = req.build_opener(proxy_opener)

        resp = None
        opener_func = req.urlopen if opener == None else opener.open

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
        except socket.timeout:
            return NETWORK_TIMEOUT, ''

        encoding = resp.info().get_content_charset('utf-8')
        content  = resp.read()
        resp.close()

        return OK, content.decode(encoding)

    @staticmethod
    def get_json(url, args, method='GET', timeout=10, proxy=''):
        error_code, result = TranslatorThread.get_http_response(url, args, method, timeout, proxy)
        json_result = {}
        try:
            json_result = json.loads(result)
        except:
            print('JSON parse error: %s' % result)
        return error_code, json_result

    def get_translations(self):
        return self.status, self.translations

class YoudaoTranslatorThread(TranslatorThread):

    KEY      = ''
    KEY_FROM = ''
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
        TranslatorThread.__init__(self, query, full_inspiration, proxy)

    def translate(self):

        args     = {
            'key':     YoudaoTranslatorThread.KEY,
            'keyfrom': YoudaoTranslatorThread.KEY_FROM,
            'type':    'data',
            'doctype': 'json',
            'version': '1.1',
            'q':       ''
        }
        args['q'] = self.query.encode('utf-8')

        result = {}
        candidates = []

        error_code, result = TranslatorThread.get_json(self.URL, args, proxy=self.proxy)
        if error_code != OK:
            return (error_code, candidates)

        if 'errorCode' in result and result['errorCode'] != 0:
            return (result['errorCode'], candidates)
        if 'translation' in result:
            for trans in result['translation']:
                candidates.append(trans)
        if 'web' in result:
            for web in result['web']:
                strictly_matched = self.query == web['key']
                if self.full_inspiration or strictly_matched:
                    for trans in web['value']:
                        candidates.append(trans)

        return (OK, candidates)

class BaiduTranslatorThread(TranslatorThread):

    APP_ID     = ''
    SECRET_KEY = ''
    URL        = 'http://api.fanyi.baidu.com/api/trans/vip/translate?'

    def __init__(self, query, full_inspiration=True, proxy=''):
        TranslatorThread.__init__(self, query, full_inspiration, proxy)

    def translate(self):

        salt = self.rand()
        args = {
            'appid': BaiduTranslatorThread.APP_ID,
            'from':  'zh',
            'to':    'en',
            'salt':  '',
            'sign':  '',
            'q':     ''
        }

        args['salt'] = salt
        args['sign'] = self.get_sign(salt)
        args['q']    = self.query

        result = {}
        candidates = []

        error_code, result = TranslatorThread.get_json(self.URL, args, proxy=self.proxy)
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

class MicrosoftTranslatorThread(TranslatorThread):

    CLIENT_ID     = ''
    CLIENT_SECRET = ''
    SCOPE         = 'http://api.microsofttranslator.com'
    GRANT_TYPE    = 'client_credentials'
    OAUTH_URL     = 'https://datamarket.accesscontrol.windows.net/v2/OAuth2-13'
    URL           = 'http://api.microsofttranslator.com/v2/Http.svc/Translate?'

    ACCESS_TOKEN_LAST_ACCQUIRED = 0
    ACCESS_TOKEN_EXPIRES_IN     = 0
    ACCESS_TOKEN_CACHE          = ''

    def __init__(self, query, full_inspiration=True, proxy=''):
        TranslatorThread.__init__(self, query, full_inspiration, proxy)

    def translate(self):

        candidates = []

        error_code = MicrosoftTranslatorThread.get_latest_token()
        if error_code != OK:
            return (error_code, candidates)

        # https://github.com/MicrosoftTranslator/PythonConsole/blob/master/MTPythonSampleCode/MTPythonSampleCode.py
        if MicrosoftTranslatorThread.is_access_token_none():
            return (999, candidates)

        from_lang   = 'zh-CHS'
        to_lang     = 'en'
        token       = MicrosoftTranslatorThread.ACCESS_TOKEN_CACHE

        # Call Microsoft Translator service
        headers = {
            'appId': token,
            'text': self.query,
            'to': to_lang
        }

        # <string xmlns="http://schemas.microsoft.com/2003/10/Serialization/">%s</string>
        error_code, translation = TranslatorThread.get_http_response(self.URL, headers, 'GET')
        if error_code != OK:
            return (error_code, candidates)

        candidates.extend(re.findall(r"<string.*>(.*)</string>", translation))

        return (OK, candidates)

    @staticmethod
    def get_latest_token():

        token_expired = MicrosoftTranslatorThread.is_access_token_expired()
        if not token_expired:
            return OK

        url  = MicrosoftTranslatorThread.OAUTH_URL
        args = {
            'client_id':     MicrosoftTranslatorThread.CLIENT_ID,
            'client_secret': MicrosoftTranslatorThread.CLIENT_SECRET,
            'scope':         MicrosoftTranslatorThread.SCOPE,
            'grant_type':    MicrosoftTranslatorThread.GRANT_TYPE
        }

        error_code, oauth_token = TranslatorThread.get_json(url, args, 'POST')
        if error_code != OK:
            return error_code

        MicrosoftTranslatorThread.ACCESS_TOKEN_CACHE          = 'Bearer %s' % oauth_token['access_token'] if 'access_token' in oauth_token else ''
        MicrosoftTranslatorThread.ACCESS_TOKEN_EXPIRES_IN     = int(oauth_token['expires_in']) if 'expires_in' in oauth_token else 0
        MicrosoftTranslatorThread.ACCESS_TOKEN_LAST_ACCQUIRED = int(time.time()) if MicrosoftTranslatorThread.ACCESS_TOKEN_CACHE != '' else 0

        return OK

    @staticmethod
    def is_access_token_expired():
        return MicrosoftTranslatorThread.ACCESS_TOKEN_CACHE == '' \
            or MicrosoftTranslatorThread.ACCESS_TOKEN_LAST_ACCQUIRED + MicrosoftTranslatorThread.ACCESS_TOKEN_EXPIRES_IN * 0.75 < int(time.time())

    @staticmethod
    def is_access_token_none():
        token = MicrosoftTranslatorThread.ACCESS_TOKEN_CACHE
        return token == None or token == ''

# Style fuction map
style_functions = {
    LOWER_CAMEL_CASE:  to_lower_camel_case,
    UPPER_CAMEL_CASE:  to_upper_camel_case,
    LOWER_UNDERSCORES: to_lower_underscores,
    UPPER_UNDERSCORES: to_upper_underscores
}

def load_microsoft_client_id():
    client_id = get_settings(MICROSOFT_CLIENT_ID, DEFAULT_MICROSOFT_CLIENT_ID)
    client_secret = get_settings(MICROSOFT_CLIENT_SECRET_KEY, DEFAULT_MICROSOFT_CLIENT_SECRET_KEY)
    MicrosoftTranslatorThread.CLIENT_ID = client_id if client_id else DEFAULT_MICROSOFT_CLIENT_ID
    MicrosoftTranslatorThread.CLIENT_SECRET = client_secret if client_secret else DEFAULT_MICROSOFT_CLIENT_SECRET_KEY

load_microsoft_client_id()
sublime.set_timeout_async(MicrosoftTranslatorThread.get_latest_token, 10)
