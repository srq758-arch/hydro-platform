"""测试 pywebview 是否能正常工作。"""

import webview

def create_test_window():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Test</title>
    </head>
    <body>
        <h1>pywebview 测试窗口</h1>
        <p>如果你能看到这个窗口，说明 pywebview 工作正常。</p>
    </body>
    </html>
    """

    window = webview.create_window(
        'Test Window',
        html=html,
        width=600,
        height=400
    )

    webview.start()

if __name__ == '__main__':
    create_test_window()
