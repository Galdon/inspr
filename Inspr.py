import sublime
import sublime_plugin
import urllib
import json
import threading

SETTING_FILE = 'Inspr.sublime-settings'

# Settings
DICTIONARY_SOURCE   = 'dictionary_source'
CASE_STYLE          = 'case_style'
MAXIMUM_QUERY_CHARS = 'maximum_query_characters'
MAXIMUM_CACHE_WORDS = 'maximum_cache_words'
CLEAR_SELECTION     = 'clear_selection'
SKIP_WORDS          = 'skip_words'
FULL_INSPIRATION    = 'full_inspiration'
ENABLE_CONTEXT_MENU = 'enable_context_menu'
PROXY               = ''

RANGE_OF_QUERY_CHARS = (1, 32)
RANGE_OF_CACHE_WORDS = (0, 32768)

# Default Settings Value
DEFAULT_DIC_SROUCE          = ['Youdao']
DEFAULT_CASE_STYLE          = 'CamelCase'
DEFAULT_MAX_QUERY_CHARS     = 32
DEFAULT_MAX_CACHE_WORDS     = 512
DEFAULT_CLEAR_SELECTION     = True
DEFAULT_SKIP_WORDS          = ["A", "a", "the", "The"]
DEFAULT_FULL_INSPIRATION    = False
DEFAULT_ENABLE_CONTEXT_MENU = True
DEFAULT_PROXY               = ''

# Youdao source
YOUDAO_API_URL  = 'http://fanyi.youdao.com/openapi.do?'
YOUDAO_API_ARGS = {
    'key':     '1787962561',
    'keyfrom': 'f2ec-org',
    'type':    'data',
    'doctype': 'json',
    'version': '1.1',
    'q':       ''
}

# Microsoft source

GLOBAL_CACHE = {}
clear_global_cache = GLOBAL_CACHE.clear

settings = sublime.load_settings(SETTING_FILE)
settings.add_on_change(DICTIONARY_SOURCE, clear_global_cache)
settings.add_on_change(MAXIMUM_QUERY_CHARS, clear_global_cache)
settings.add_on_change(MAXIMUM_CACHE_WORDS, clear_global_cache)
settings.add_on_change(FULL_INSPIRATION, clear_global_cache)
settings.add_on_change(SKIP_WORDS, clear_global_cache)
settings.add_on_change(PROXY, clear_global_cache)

def upper_camel_case(x):
    s = ''.join(a for a in x.title() if not a.isspace())
    return s

def lower_camel_case(x):
    s = upper_camel_case(x)
    lst = [word[0].lower() + word[1:] for word in s.split()]
    s = ''.join(lst)
    return s

def get_response_json(base_url, args):
    url = base_url + urllib.parse.urlencode(args)
    response = urllib.request.urlopen(url)

    data = response.read()
    encoding = response.info().get_content_charset('utf-8')
    result = json.loads(data.decode(encoding))

    return result

class InsprReplaceSelectionCommand(sublime_plugin.TextCommand):

    def run(self, edit, **replacement):

        if 'text' not in replacement:
            return

        view = self.view
        selection = view.sel()
        translation = replacement['text']

        view.replace(edit, selection[0], translation)

        clear_selection = settings.get(CLEAR_SELECTION, DEFAULT_CLEAR_SELECTION)
        if clear_selection == False:
            return

        pt = selection[0].end()

        selection.clear()
        selection.add(sublime.Region(pt))

        view.show(pt)

class InsprCommand(sublime_plugin.TextCommand):

    def run(self, edit, **args):
        InsprQueryThread(edit, self.view, **args).start()

class InsprQueryThread(threading.Thread):

    def __init__(self, edit, view, **args):
        self.edit = edit
        self.view = view
        self.window = view.window()
        self.available_trans = []
        self.args = args
        threading.Thread.__init__(self)

    def run(self):

        cache = GLOBAL_CACHE

        sel = self.view.substr(self.view.sel()[0])
        if sel == '':
            return

        # if cache hit
        if sel in cache:
            cache_styles = cache[sel]
            code_style = self.args['camel_case_type']
            if code_style in cache_styles:
                cache_trans = cache_styles[code_style]
                self.available_trans = cache_trans
                self.view.window().show_quick_panel(self.available_trans, self.on_done)
                return

        YOUDAO_API_ARGS['q'] = sel
        result = get_response_json(YOUDAO_API_URL, YOUDAO_API_ARGS)

        if 'errorCode' in result:
            if result['errorCode'] != 0:
                return

        candidates = []

        if 'translation' in result:
            for v in result['translation']:
                candidates.append(v)
        if 'web' in result:
            full_inspiration = settings.get(FULL_INSPIRATION, DEFAULT_FULL_INSPIRATION)
            for web in result['web']:
                match_sel = sel == web['key']
                value = web['value']
                if full_inspiration or match_sel:
                    for v in web['value']:
                        candidates.append(v)

        case_style = self.args['camel_case_type']

        for trans in candidates:
            case = upper_camel_case(trans) if case_style == 'upper' else lower_camel_case(trans)
            self.available_trans.append(case)

        self.available_trans = sorted(set(self.available_trans))

        def cache_words():
            cache_words_count = settings.get(MAXIMUM_CACHE_WORDS, DEFAULT_MAX_CACHE_WORDS)
            if len(cache.keys()) > cache_words_count:
                cache.clear()

            if sel not in cache:
                cache[sel] = {}

            if case_style not in cache[sel]:
                cache[sel][case_style] = []

            cache[sel][case_style] = self.available_trans

        cache_words()
        self.window.show_quick_panel(self.available_trans, self.on_done)

    def on_done(self, picked):

        if picked == -1:
            return
        trans = self.available_trans[picked]

        args = { 'text': trans }
        def replace_selection():
            self.view.run_command("inspr_replace_selection", args)

        sublime.set_timeout(replace_selection, 10)
