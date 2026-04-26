"""
로컬 테스트용 HTTP 서버
=======================
viewer.html은 데이터를 외부 .js 파일에서 fetch하므로 file:// 더블클릭으로 열면
브라우저 보안(CORS) 때문에 작동하지 않습니다.
이 스크립트로 로컬 서버를 띄워서 http://localhost:8000/viewer.html 로 열면 정상 작동합니다.

사용법:
    python serve.py
    → 브라우저에서 http://localhost:8000/viewer.html 열림 (자동)

종료: Ctrl+C
"""

import http.server
import os
import socketserver
import sys
import webbrowser

PORT = 8000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    os.chdir(SCRIPT_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    # 한국어 파일명 + UTF-8 처리
    handler.extensions_map.setdefault(".js", "application/javascript;charset=utf-8")
    handler.extensions_map.setdefault(".json", "application/json;charset=utf-8")

    try:
        with socketserver.TCPServer(("", PORT), handler) as httpd:
            url = f"http://localhost:{PORT}/viewer.html"
            print(f"\n📡 로컬 서버 시작: {url}")
            print(f"📁 폴더: {SCRIPT_DIR}")
            print("   브라우저에서 위 주소를 열면 뷰어가 표시됩니다.")
            print("   종료하려면 Ctrl+C")
            print()
            try:
                webbrowser.open(url)
            except Exception:
                pass
            httpd.serve_forever()
    except OSError as e:
        if "Address already in use" in str(e) or e.errno == 10048:
            print(f"❌ 포트 {PORT}이 이미 사용 중입니다. 기존 서버를 종료하거나 PORT를 바꾸세요.")
            sys.exit(1)
        raise
    except KeyboardInterrupt:
        print("\n\n서버 종료.")


if __name__ == "__main__":
    main()
