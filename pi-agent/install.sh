#!/usr/bin/env bash
set -euo pipefail

# Installs only into the chosen user's directories. Models and history live
# outside the application directory, so replacing the application preserves them.
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${XDG_DATA_HOME:-$HOME/.local/share}/solrdm-pi"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
launch=1
build_runtime=0
while (($#)); do
  case "$1" in
    --install-dir) install_dir="$2"; shift 2 ;;
    --desktop-dir) desktop_dir="$2"; shift 2 ;;
    --no-launch) launch=0; shift ;;
    --build-runtime) build_runtime=1; shift ;;
    --help) printf '%s\n' 'Usage: ./install.sh [--no-launch] [--install-dir DIR] [--desktop-dir DIR] [--build-runtime]'; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 ]]; then
  printf '%s\n' 'This runtime package requires 64-bit ARM Linux (aarch64), such as 64-bit Raspberry Pi OS on Pi 5.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'

if [[ -f "$source_dir/MANIFEST.sha256" ]]; then
  (cd "$source_dir" && sha256sum --check --quiet MANIFEST.sha256)
fi

if ((build_runtime)); then
  for command_name in git cmake c++; do
    command -v "$command_name" >/dev/null || {
      printf '%s\n' 'Source build needs: sudo apt-get update && sudo apt-get install -y build-essential cmake git' >&2
      exit 1
    }
  done
  build_dir="$(mktemp -d)"
  trap 'rm -rf -- "$build_dir"' EXIT
  git -C "$build_dir" init -q
  git -C "$build_dir" remote add origin https://github.com/ggml-org/llama.cpp.git
  git -C "$build_dir" fetch --depth=1 origin 8642541b255bfb5dc39cd351a178be09013a55d6
  git -C "$build_dir" checkout --detach FETCH_HEAD
  test "$(git -C "$build_dir" rev-parse HEAD)" = 8642541b255bfb5dc39cd351a178be09013a55d6
  cmake -S "$build_dir" -B "$build_dir/build" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8-a \
    -DGGML_OPENMP=OFF -DLLAMA_OPENSSL=OFF -DLLAMA_SUBPROCESS=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_APP=OFF \
    -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
    '-DCMAKE_EXE_LINKER_FLAGS=-static-libgcc -static-libstdc++'
  cmake --build "$build_dir/build" --target llama-server -j 2
  mkdir -p "$source_dir/runtime/bin"
  cp "$build_dir/build/bin/llama-server" "$source_dir/runtime/bin/llama-server"
  cp "$build_dir/LICENSE" "$source_dir/runtime/LICENSE-llama.cpp.txt"
fi

if [[ ! -x "$source_dir/runtime/bin/llama-server" ]]; then
  printf '%s\n' 'The ARM64 runtime is missing. Download the linux-arm64 package, or run ./install.sh --build-runtime after installing the listed build tools.' >&2
  exit 1
fi
"$source_dir/runtime/bin/llama-server" --version

python3 - "$source_dir" "$install_dir" "$desktop_dir" "$build_runtime" <<'PY'
import fcntl, hashlib, json, os, pathlib, shutil, signal, sys, tempfile, time
source, destination, desktop = [pathlib.Path(p).expanduser().resolve() for p in sys.argv[1:4]]
runtime_rebuilt = sys.argv[4] == '1'
if destination == source or source.is_relative_to(destination) or destination.is_relative_to(source):
    raise SystemExit('Install into a separate directory, outside the extracted package.')
destination.mkdir(parents=True, exist_ok=True, mode=0o700)
data = destination / 'data'
data.mkdir(exist_ok=True, mode=0o700)
lock = (data / 'launcher.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX)
# Stop only the exact installed Python service, never an unrelated reused PID.
pid_file = data / 'server.pid'
if pid_file.exists():
    try:
        pid = int(pid_file.read_text().strip())
        process = pathlib.Path('/proc') / str(pid)
        argv = (process / 'cmdline').read_bytes().split(b'\0')
        owned = (pid > 1 and process.stat().st_uid == os.getuid()
                 and (process / 'cwd').resolve() == (destination / 'app').resolve()
                 and [b'-m', b'solrdm_pi'] in [argv[i:i + 2] for i in range(len(argv) - 1)])
        if owned:
            print('Stopping the previous SOLRDM application before updating.')
            os.kill(pid, signal.SIGTERM)
            for attempt in range(100):
                if not process.exists():
                    break
                time.sleep(0.1)
            else:
                raise SystemExit('The previous app did not stop; close it and run the installer again. No application files were replaced.')
        else:
            print('Ignoring a stale process ID belonging to another process.')
    except (ValueError, FileNotFoundError, ProcessLookupError):
        pass
    pid_file.unlink(missing_ok=True)
staging = pathlib.Path(tempfile.mkdtemp(prefix='.app-new-', dir=destination))
try:
    for name in ['solrdm_pi', 'web', 'runtime', 'engine']:
        if (source / name).is_dir():
            shutil.copytree(source / name, staging / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['install.sh', 'launch.sh', 'README.md', 'BUILD-INFO.json', 'MANIFEST.sha256', 'source-provenance.json']:
        if (source / name).is_file():
            shutil.copy2(source / name, staging / name)
    if not (staging / 'engine/solrdm').is_dir():
        engine_source = source.parent / 'app/src/main/python'
        provenance = source.parent / 'docs/source-provenance.json'
        if not (engine_source / 'solrdm').is_dir() or not provenance.is_file():
            raise SystemExit('The complete SOLRDM engine is missing. Install the complete release archive or a full repository checkout.')
        (staging / 'engine').mkdir(exist_ok=True)
        shutil.copytree(engine_source / 'solrdm', staging / 'engine/solrdm', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(engine_source / 'android_bridge.py', staging / 'engine/android_bridge.py')
        shutil.copy2(provenance, staging / 'source-provenance.json')
    (staging / 'launch.sh').chmod(0o755)
    (staging / 'runtime/bin/llama-server').chmod(0o755)
    if runtime_rebuilt:
        info_path = staging / 'BUILD-INFO.json'
        info = json.loads(info_path.read_text()) if info_path.is_file() else {'application': 'SOLRDM Pi Agent', 'version': '0.9.0', 'build_url': None}
        info.update(runtime_rebuilt_locally=True, llama_cpp_commit='8642541b255bfb5dc39cd351a178be09013a55d6')
        info_path.write_text(json.dumps(info, indent=2) + '\n')
        manifest = []
        for file in sorted(staging.rglob('*')):
            if file.is_file() and file.name != 'MANIFEST.sha256':
                with file.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                manifest.append(digest + '  ' + str(file.relative_to(staging)) + '\n')
        (staging / 'MANIFEST.sha256').write_text(''.join(manifest))
    old = destination / 'app.previous'
    current = destination / 'app'
    if old.exists():
        shutil.rmtree(old)
    if current.exists():
        current.rename(old)
    try:
        staging.rename(current)
    except BaseException:
        if old.exists() and not current.exists():
            old.rename(current)
        raise
except BaseException:
    if staging.exists():
        shutil.rmtree(staging)
    raise
desktop.mkdir(parents=True, exist_ok=True)
def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
launcher = current / 'launch.sh'
entry = '\n'.join([
    '[Desktop Entry]', 'Type=Application', 'Name=SOLRDM Pi Agent',
    'Comment=Local models, research and scientific tools',
    'Exec=' + quote(launcher), 'Icon=applications-science',
    'Terminal=false', 'Categories=Education;Science;', 'StartupNotify=true', ''
])
desktop_file = desktop / 'solrdm-pi.desktop'
desktop_file.write_text(entry, encoding='utf-8')
desktop_file.chmod(0o755)
print('Installed application:', current)
print('Private models, settings and memory:', data)
print('Desktop menu entry:', desktop_file)
PY

if ! command -v pdftotext >/dev/null; then
  printf '%s\n' 'Optional PDF text extraction: sudo apt-get install poppler-utils'
fi
printf '%s\n' 'Open SOLRDM Pi Agent from the application menu. Model weights are separate downloads in the Models tab.'
if ((launch)); then
  "$install_dir/app/launch.sh"
fi
