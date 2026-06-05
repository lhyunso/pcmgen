#!/usr/bin/env python3
"""
버전 일괄 업데이트 스크립트
사용법: python3 bump_version.py v1.2.0
"""
import re, sys, subprocess
from pathlib import Path

ROOT = Path(__file__).parent

TARGETS = [
    # (파일, 패턴, 치환 함수)
    (ROOT / "ui/index.html",
     r'(border-radius:20px;[^>]+>)v\d+\.\d+\.\d+(<)',
     lambda v, m: m.group(1) + v + m.group(2)),
    (ROOT / "ui/index.html",
     r"(const APP_VERSION = ')v\d+\.\d+\.\d+(')",
     lambda v, m: m.group(1) + v + m.group(2)),
]

def bump(new_ver: str):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', new_ver):
        print(f"❌ 버전 형식 오류: {new_ver}  (예: v1.2.0)")
        sys.exit(1)

    changed = []
    for path, pattern, replacer in TARGETS:
        text = path.read_text(encoding="utf-8")
        new_text, n = re.subn(pattern, lambda m: replacer(new_ver, m), text)
        if n:
            path.write_text(new_text, encoding="utf-8")
            changed.append(f"  ✅ {path.name}  ({n}곳)")

    if changed:
        print(f"버전 → {new_ver}")
        for c in changed: print(c)
    else:
        print("⚠️  변경된 항목 없음 (패턴 불일치)")

    # 현재 버전 확인
    text = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    m = re.search(r"const APP_VERSION = '(v[^']+)'", text)
    print(f"APP_VERSION 확인: {m.group(1) if m else '?'}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python3 bump_version.py v1.2.0")
        sys.exit(1)
    bump(sys.argv[1])
