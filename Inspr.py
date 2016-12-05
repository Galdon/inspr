import hashlib
import json
import random
import re
import sublime
import sublime_plugin
import threading
import urllib
from socket import timeout

SETTINGS_FILE = 'Inspr.sublime-settings'

MAXIMUM_QUERY_CHARS = 32
MAXIMUM_CACHE_WORDS = 32768

# Case styles
LOWER_CAMEL_CASE  = 'lower_camel_case'
UPPER_CAMEL_CASE  = 'upper_camel_case'
LOWER_UNDERSCORES = 'lower_underscores'
UPPER_UNDERSCORES = 'upper_underscores'

# Settings
DICTIONARY_SOURCE   = 'dictionary_source'
CLEAR_SELECTION     = 'clear_selection'
AUTO_DETECT_WORDS   = 'auto_detect_words'
SKIP_WORDS          = 'skip_words'
FULL_INSPIRATION    = 'full_inspiration'
ENABLE_CONTEXT_MENU = 'enable_context_menu'
PROXY               = ''

# Default Settings Value
DEFAULT_DIC_SROUCE          = ['Baidu']
DEFAULT_CLEAR_SELECTION     = True
DEFAULT_AUTO_DETECT_WORDS   = True
DEFAULT_SKIP_WORDS          = ["A", "a", "the", "The"]
DEFAULT_FULL_INSPIRATION    = False
DEFAULT_ENABLE_CONTEXT_MENU = True
DEFAULT_PROXY               = ''

DICTIONARY_CACHE = {}
clear_global_cache = DICTIONARY_CACHE.clear

settings = sublime.load_settings(SETTINGS_FILE)
settings.add_on_change(DICTIONARY_SOURCE,   clear_global_cache)
settings.add_on_change(FULL_INSPIRATION,    clear_global_cache)
settings.add_on_change(SKIP_WORDS,          clear_global_cache)
settings.add_on_change(PROXY,               clear_global_cache)

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

        word = self.view.substr(self.view.sel()[0]).strip()
        if settings.get(AUTO_DETECT_WORDS, DEFAULT_AUTO_DETECT_WORDS):
            word = '' # detect_nearest_selection(word)
        if len(word) == 0 or word.isspace():
            return

        self.window.status_message('Search for: ' + word + '...')

        # if cache hit
        if self.is_cache_hit(cache, word, case_style):
            cached_trans = cache[word][case_style]
            self.window.show_quick_panel(cached_trans, self.on_done)
            return

        # select source
        candidates = []
        dic_source = settings.get(DICTIONARY_SOURCE, DEFAULT_DIC_SROUCE)

        if dic_source == None:
            dic_source = DEFAULT_DIC_SROUCE

        # set proxy
        # set_proxy_if_available()

        for dic in dic_source:
            if dic in translator_map:
                candidates += translator_map[dic].translate(word)

        for trans in candidates:
            case = style_function(trans)
            self.translations.append(case)

        def isidentifier(string):
            return re.match('[0-9a-zA-Z_]+', string) != None

        for idx, val in enumerate(self.translations):
            self.translations[idx] = re.sub('[-.:/]', '', val)
        self.translations = sorted(filter(isidentifier, set(self.translations)))

        self.cache_words(cache, word, case_style)
        self.window.show_quick_panel(self.translations, self.on_done)

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

class YoudaoTranslator(object):

    KEY      = '1787962561'
    KEY_FROM = 'f2ec-org'
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

        self.ARGS['q'] = query

        result = get_json_content(self.URL, self.ARGS)
        candidates = []

        if 'errorCode' in result:
            if result['errorCode'] != 0:
                return candidates
        if 'translation' in result:
            for trans in result['translation']:
                candidates.append(trans)
        if 'web' in result:
            full_inspr = settings.get(FULL_INSPIRATION, DEFAULT_FULL_INSPIRATION)
            for web in result['web']:
                strictly_matched = query == web['key']
                if full_inspr or strictly_matched:
                    for trans in web['value']:
                        candidates.append(trans)

        return candidates

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

        result = get_json_content(self.URL, self.ARGS)
        candidates = []

        if 'error_code' in result:
            return candidates

        if 'trans_result' in result:
            for trans in result['trans_result']:
                candidates.append(trans['dst'])

        return candidates

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

    url = base_url + urllib.parse.urlencode(args)
    response = urllib.request.urlopen(url, timeout=10)

    data     = response.read()
    encoding = response.info().get_content_charset('utf-8')
    result   = json.loads(data.decode(encoding))

    response.close()

    return result
