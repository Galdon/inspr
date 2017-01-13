# Inspr

A tranlation plugin for Sublime Text 3 that helps Chinese programmers to name variables and traslate Chinese words to English with specific variable format.

# Installation

[Latest Release](https://github.com/wzhix/inspr/releases/latest)

# Usage

Input the variable name you want to translate in Chinese and press shortcut keys, the plugin will translate them to English with specific format.

There are 4 types of variable format available --- `lowerCamelCase`, `UpperCamelCase`, `lower_underscores` and `UPPER_UNDERSCORES`, each of them has its corresponding  key-mapping.

For example, `let 普通变量 (Ctrl + Command + i)`, a quick panel will popup up and show the variable-formated results as `commonVariable`, `commonVariables`, `geheric` and `ordinaryVariable`.

# Demonstration

![插件效果](inspr-demo.gif)

# Settings

### 词典源（Dictionary Source）

Inspr provides 3 dictionaries by default --- 有道翻译(Youdao), 百度翻译(Baidu) and 微软翻译(Microsoft). Valid options are "Youdao", "Baidu", "Microsoft", `["Youdao", "Baidu"]` is recommended.
```
"dictionary_source": ["Youdao", "Baidu"]
```

### 清除选中（Clear Selection）

If true, the selection in current editor will clear after the item in quick panel is selected. `true` is recommended.
```
"clear_selection": true
```

### 自动检测单词（Auto Detect Words）

If true, Inspr will search word toward left and right. `true` is recommended.
```
"auto_detect_words": true
```

### 忽略单词（Ignore Words）

Words in this list will be skiped when processing. `["A", "a", "the", "The"]` is recommended.
```
"ignore_words": ["A", "a", "the", "The"]
```

### 完整提示（Full Inspiration)

If true, web translations will be added in results. Inspr will provide less accurated results but it will be more candidate translations in results. `true` is recommended.
```
"full_inspiration": true
```

### 结果显示为等宽字体（Show with Monospace Font）

If true, results in quick panel will be rendered with monospace font. `false` is recommended.
```
"show_with_monospace_font": false
```

### HTTP 代理（HTTP Proxy）

Connect translation API server with http proxy.
```
"http_proxy": ""
```
# License

```
Copyright 2017 zhix

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
