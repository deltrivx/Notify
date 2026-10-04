#!/bin/bash
# 静态自检：shell 语法 / YAML 合法 / Python 编译 / 无真实凭据
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
rc=0
say() { printf '%-8s %s\n' "$1" "$2"; }

# 1) shell 语法
while IFS= read -r f; do
  if bash -n "$f"; then say OK "$f"; else say FAIL "$f"; rc=1; fi
done < <(find . -name '*.sh' -not -path './.git/*')

# 2) Python 编译
while IFS= read -r f; do
  if python3 -m py_compile "$f" 2>/dev/null; then say OK "$f"; else say FAIL "$f"; rc=1; fi
done < <(find . -name '*.py' -not -path './.git/*')
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null

# 3) YAML 合法（含 workflow）
python3 - <<'PY'
import glob, sys, yaml
bad = []
for f in glob.glob('.github/workflows/*.yml') + glob.glob('docker/*.yml') + glob.glob('*.yml'):
    try:
        yaml.safe_load(open(f, encoding='utf-8'))
        print('OK      ', f)
    except Exception as e:
        bad.append((f, str(e))); print('FAIL    ', f, e)
sys.exit(1 if bad else 0)
PY
[ $? -ne 0 ] && rc=1

# 4) 无真实凭据
if grep -rInE "(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,})" \
     --exclude-dir=.git . 2>/dev/null; then
  say FAIL "疑似真实凭据"; rc=1
else
  say OK "无真实凭据"
fi

exit $rc
