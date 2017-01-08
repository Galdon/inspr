import codecs
import hashlib
import json
import random
import re
import sublime
import sublime_plugin
import threading
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
    54005:           '百度：长 query 请求频繁，请降低长 query 的发送频率'
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

settings = sublime.load_settings(SETTINGS_FILE)
settings.add_on_change(DICTIONARY_SOURCE,   clear_global_cache)
settings.add_on_change(FULL_INSPIRATION,    clear_global_cache)
settings.add_on_change(IGNORE_WORDS,        clear_global_cache)
settings.add_on_change(HTTP_PROXY,          clear_global_cache)

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
        if sel.begin() == sel.end() and settings.get(AUTO_DETECT_WORDS, DEFAULT_AUTO_DETECT_WORDS):
            self.view.run_command("inspr_auto_detect_words")

        word = self.view.substr(self.view.sel()[0]).strip()
        if len(word) == 0 or word.isspace():
            return

        self.window.status_message('Search for: ' + word + '...')

        # if cache hit
        if self.is_cache_hit(cache, word, case_style):
            self.translations += cache[word][case_style]
            self.window.show_quick_panel(self.translations, self.on_done)
            return

        # select source
        cause = 0
        causes = []
        candidates = []
        dic_source = settings.get(DICTIONARY_SOURCE, DEFAULT_DIC_SROUCE)

        if dic_source == None:
            dic_source = DEFAULT_DIC_SROUCE

        for dic in dic_source:
            if dic in translator_map:
                (c, candidate) = translator_map[dic].translate(word)
                causes.append(c)
                candidates += candidate

        if OK not in causes:
            cause = causes[0]

        ignore = settings.get(IGNORE_WORDS, DEFAULT_IGNORE_WORDS)

        for trans in candidates:
            # split by space and skip words
            if ignore:
                trans = ignore_and_filter(trans, ignore)
            case = style_function(trans)
            self.translations.append(case)

        def isidentifier(string):
            return re.match('[0-9a-zA-Z_]+', string) != None

        for idx, val in enumerate(self.translations):
            self.translations[idx] = re.sub('[-.:/,]', '', val)
        self.translations = sorted(filter(isidentifier, set(self.translations)))

        if self.translations and cause == OK:
            self.cache_words(cache, word, case_style)
            if settings.get(SHOW_WITH_MONOSPACE_FONT, DEFAULT_SHOW_WITH_MONOSPACE_FONT):
                self.window.show_quick_panel(self.translations, self.on_done, sublime.MONOSPACE_FONT)
            else:
                self.window.show_quick_panel(self.translations, self.on_done)
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

        clear_sel = settings.get(CLEAR_SELECTION, DEFAULT_CLEAR_SELECTION)
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

class YoudaoTranslator(object):

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

    def translate(self, query):

        self.ARGS['q'] = query.encode('utf-8')

        result = {}
        candidates = []

        try:
            result = get_json_content(self.URL, self.ARGS)
        except urllib.error.URLError:
            return (NETWORK_TIMEOUT, candidates)

        if 'errorCode' in result:
            if result['errorCode'] != 0:
                return (result['errorCode'], candidates)
        if 'translation' in result:
            for trans in result['translation']:
                candidates.append(trans)
        full_inspr = settings.get(FULL_INSPIRATION, DEFAULT_FULL_INSPIRATION)
        if 'web' in result:
            for web in result['web']:
                strictly_matched = query == web['key']
                if full_inspr or strictly_matched:
                    for trans in web['value']:
                        candidates.append(trans)

        return (OK, candidates)

class BaiduTranslator(object):

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

    def translate(self, query):

        salt = self.rand()

        self.ARGS['salt'] = salt
        self.ARGS['sign'] = self.get_sign(salt, query)
        self.ARGS['q']    = query

        result = {}
        candidates = []

        try:
            result = get_json_content(self.URL, self.ARGS)
        except urllib.error.URLError:
            return (NETWORK_TIMEOUT, candidates)

        if 'error_code' in result:
            return (result['error_code'], candidates)

        if 'trans_result' in result:
            for trans in result['trans_result']:
                candidates.append(trans['dst'])

        return (OK, candidates)

    def rand(self):
        return random.randint(32768, 65536)

    def get_sign(self, salt, query):
        sign = self.APP_ID + query + str(salt) + self.SECRET_KEY
        md5  = hashlib.md5()
        md5.update(sign.encode('utf-8'))
        sign = md5.hexdigest()
        return sign

# Youdao source
youdao_client = YoudaoTranslator()

# Baidu source
baidu_client  = BaiduTranslator()

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
    'Baidu':  baidu_client
}

def get_corresponding_style_function(case_style):
    mapper = style_functions
    return mapper[case_style] if case_style in mapper else to_lower_camel_case

def get_json_content(base_url, args):

    req = urllib.request

    # set proxy
    proxy = settings.get(HTTP_PROXY, DEFAULT_HTTP_PROXY)

    opener = None
    if proxy != '' and proxy != None:
        proxy_opener = req.ProxyHandler({'http': proxy})
        opener = req.build_opener(proxy_opener)

    url = base_url + urllib.parse.urlencode(args)

    response = None
    if opener != None:
        response = opener.open(url, timeout=5)
    else:
        response = req.urlopen(url, timeout=5)

    data     = response.read()
    encoding = response.info().get_content_charset('utf-8')
    result   = json.loads(data.decode(encoding))

    response.close()

    return result
