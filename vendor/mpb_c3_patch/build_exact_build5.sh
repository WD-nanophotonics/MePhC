#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: build_exact_build5.sh SOURCE_ARCHIVE EMPTY_BUILD_DIR EMPTY_PREFIX" >&2
  exit 2
fi

source_archive=$(realpath "$1")
build_dir=$(realpath -m "$2")
install_prefix=$(realpath -m "$3")
expected_source=8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4

[[ -f "$source_archive" ]] || { echo "source archive missing" >&2; exit 3; }
[[ $(sha256sum "$source_archive" | awk '{print $1}') == "$expected_source" ]] || { echo "source hash mismatch" >&2; exit 4; }
[[ "$build_dir" == /* && "$install_prefix" == /* && "$build_dir" != / && "$install_prefix" != / ]] || { echo "isolated absolute paths required" >&2; exit 5; }
[[ -z "${CONDA_PREFIX:-}" || "$install_prefix" != "$(realpath -m "$CONDA_PREFIX")" ]] || { echo "active environment is immutable" >&2; exit 6; }
[[ ! -e "$build_dir" && ! -e "$install_prefix" ]] || { echo "fresh build and prefix required" >&2; exit 7; }

mkdir -p "$build_dir/source" "$install_prefix"
tar -xzf "$source_archive" --strip-components=1 -C "$build_dir/source"
cd "$build_dir/source"

gnuconfig_root=""
for candidate in "${MPB_GNUCONFIG_ROOT:-}" "${MPB_BUILD_PREFIX:+$MPB_BUILD_PREFIX/share/gnuconfig}" "${MPB_DEP_PREFIX:+$MPB_DEP_PREFIX/share/gnuconfig}"; do
  if [[ -n "$candidate" && -f "$candidate/config.sub" && -f "$candidate/config.guess" ]]; then
    gnuconfig_root=$(realpath "$candidate")
    break
  fi
done
[[ -n "$gnuconfig_root" ]] || { echo "gnuconfig unavailable: provide MPB_GNUCONFIG_ROOT, MPB_BUILD_PREFIX, or MPB_DEP_PREFIX" >&2; exit 8; }
echo "GNUCONFIG_ROOT=$gnuconfig_root"
echo "GNUCONFIG_CONFIG_SUB_SHA256=$(sha256sum "$gnuconfig_root/config.sub" | awk '{print $1}')"
echo "GNUCONFIG_CONFIG_GUESS_SHA256=$(sha256sum "$gnuconfig_root/config.guess" | awk '{print $1}')"
cp "$gnuconfig_root/config.sub" "$gnuconfig_root/config.guess" .

if [[ -n "${MPB_PATCH_FILE:-}" ]]; then
  patch_file=$(realpath "$MPB_PATCH_FILE")
  [[ -f "$patch_file" ]] || { echo "patch missing" >&2; exit 9; }
  patch --batch --forward -p1 < "$patch_file"
fi

export CC=${MPB_CC:-mpicc}
export CXX=${MPB_CXX:-mpicxx}
export CPPFLAGS="-I${MPB_DEP_PREFIX:-${CONDA_PREFIX:?}}/include ${CPPFLAGS:-}"
export LDFLAGS="-L${MPB_DEP_PREFIX:-${CONDA_PREFIX:?}}/lib -Wl,-rpath,${MPB_DEP_PREFIX:-${CONDA_PREFIX:?}}/lib ${LDFLAGS:-}"
./configure --prefix="$install_prefix" --enable-shared --with-libctl=no --with-hermitian-eps --disable-dependency-tracking
make -j "${MPB_BUILD_JOBS:-1}"
make check
make install
sha256sum "$install_prefix"/lib/libmpb.so* | sort
