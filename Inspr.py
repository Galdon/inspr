import sublime
import sublime_plugin
import urllib
import json

SETTING_FILE = "Inspr.sublime-settings"

YOUDAO_API_URL  = 'http://fanyi.youdao.com/openapi.do?'
YOUDAO_API_ARGS = {
    'key':     '1787962561',
    'keyfrom': 'f2ec-org',
    'type':    'data',
    'doctype': 'json',
    'version': '1.1',
    'q':       ''
}

MAXIMUM_CACHE_SIZE = 512

GLOBAL_CACHE = {}

class InsprReplaceSelectionCommand(sublime_plugin.TextCommand):

    def run(self, edit, **replacement):

        if 'text' not in replacement:
            return

        view = self.view
        selection = view.sel()
        translation = replacement['text']

        view.replace(edit, selection[0], translation)
        pt = selection[0].end()

        selection.clear()
        selection.add(sublime.Region(pt))

        view.show(pt)

class InsprCommand(sublime_plugin.TextCommand):

    def run(self, edit, **args):

        view = self.view
        self.available_trans = []
        cache = GLOBAL_CACHE

        sel = view.substr(view.sel()[0])
        if sel == '':
            return

        # if cache hit
        if sel in cache:
            cache_styles = cache[sel]
            code_style = args['camel_case_type']
            if code_style in cache_styles:
                cache_trans = cache_styles[code_style]
                self.available_trans = cache_trans
                view.window().show_quick_panel(self.available_trans, self.on_done)
                return

        YOUDAO_API_ARGS['q'] = sel

        url = YOUDAO_API_URL + urllib.parse.urlencode(YOUDAO_API_ARGS)
        response = urllib.request.urlopen(url)

        data = response.read()
        encoding = response.info().get_content_charset('utf-8')
        result = json.loads(data.decode(encoding))

        if 'errorCode' in result:
            if result['errorCode'] != 0:
                return

        candidates = []

        if 'translation' in result:
            for v in result['translation']:
                candidates.append(v)
        if 'web' in result:
            for web in result['web']:
                if web['key'] == sel:
                    value = web['value']
                    for v in value:
                        candidates.append(v)

        case_style = args['camel_case_type']

        for trans in candidates:
            case = ''
            if case_style == 'upper':
                case = self.upper_camel_case(trans)
            else:
                case = self.lower_camel_case(trans)
            self.available_trans.append(case)

        self.available_trans = sorted(set(self.available_trans))

        if len(cache.keys()) > MAXIMUM_CACHE_SIZE:
            cache.clear()

        if sel not in cache:
            cache[sel] = {}
        if case_style not in cache[sel]:
            cache[sel][case_style] = []
        cache[sel][case_style] = self.available_trans

        view.window().show_quick_panel(self.available_trans, self.on_done)

    def upper_camel_case(self, x):
        s = ''.join(a for a in x.title() if not a.isspace())
        return s

    def lower_camel_case(self, x):
        s = self.upper_camel_case(x)
        lst = [word[0].lower() + word[1:] for word in s.split()]
        s = ''.join(lst)
        return s

    def on_done(self, picked):

        if picked == -1:
            return
        trans = self.available_trans[picked]

        args = { 'text': trans }
        def replace_selection():
            self.view.run_command("inspr_replace_selection", args)

        sublime.set_timeout(replace_selection, 10)
