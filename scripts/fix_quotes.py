#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 app.js 中的 HTML 属性引号问题"""

import re
import sys
import io

# 设置UTF-8输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 读取文件
with open('F:/hydro_platform_v1/hydro_platform/app/web/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 renderTestLab 函数的 innerHTML 赋值中，将所有 class="..." 改为 class='...'
# 将所有 style="..." 改为 style='...'
# 将所有 onclick="..." 改为 onclick='...'

# 找到 renderTestLab 函数中的模板字符串 (从第846行到第916行)
lines = content.split('\n')

# 只修改 renderTestLab 函数内的 innerHTML 模板字符串部分 (第846-916行)
for i in range(845, 916):  # 0-indexed, 所以是845到915
    line = lines[i]
    # 替换HTML属性中的双引号为单引号
    # class="..." -> class='...'
    line = re.sub(r'class="([^"]*)"', r"class='\1'", line)
    # style="..." -> style='...'
    line = re.sub(r'style="([^"]*)"', r"style='\1'", line)
    # onclick="..." -> onclick='...'
    line = re.sub(r'onclick="([^"]*)"', r"onclick='\1'", line)
    lines[i] = line

# 重新组装
content = '\n'.join(lines)

# 写回文件
with open('F:/hydro_platform_v1/hydro_platform/app/web/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 修复完成！已将 renderTestLab 函数中的 HTML 属性双引号改为单引号")
