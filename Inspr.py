import sublime
import sublime_plugin
import urllib
import json

SETTING_FILE = "Inspr.sublime-settings"
YOUDAO_URL   = "http://fanyi.youdao.com/openapi.do?"

KEY = "1787962561"
KEYFROM = "f2ec-org"
TYPE = "data"
DOCTYPE = "json"
VERSION = "1.1"

class InsprReplaceSelectionCommand(sublime_plugin.TextCommand):
    def run(self, edit, **replacement):
        view = self.view
        view.replace(edit, view.sel()[0], replacement['text'])

        pt = view.sel()[0].end()

        view.sel().clear()
        view.sel().add(sublime.Region(pt))

        view.show(pt)

class InsprCommand(sublime_plugin.TextCommand):
    def run(self, edit, **args):

        sel = self.view.substr(self.view.sel()[0])
        if sel == '':
            return

        query = {
            'key': KEY,
            'keyfrom': KEYFROM,
            'type': TYPE,
            'doctype': DOCTYPE,
            'version': VERSION,
            'q': sel
        }
        response = urllib.request.urlopen(YOUDAO_URL + urllib.parse.urlencode(query))

        data = response.read()
        encoding = response.info().get_content_charset('utf-8')
        result = json.loads(data.decode(encoding))


        self.available_trans = []
        if 'translation' in result:
            for x in result['translation']:
                case = ""
                if args['camel_case_type'] == 'upper':
                    case = self.upper_camel_case(x)
                else:
                    case = self.lower_camel_case(x)
                self.available_trans.append(case)
        if 'web' in result:
            for web in result['web']:
                if web['key'] == sel:
                    case = ""
                    for x in web['value']:
                        if args['camel_case_type'] == 'upper':
                            case = self.upper_camel_case(x)
                        else:
                            case = self.lower_camel_case(x)
                        self.available_trans.append(case)
        self.available_trans = sorted(set(self.available_trans), key=self.available_trans.index)
        self.view.window().show_quick_panel(self.available_trans, self.on_done)

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
