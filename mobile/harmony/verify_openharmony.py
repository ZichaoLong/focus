#!/usr/bin/env python3
"""Compile and package the shell against a public OpenHarmony SDK for CI."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", required=True, type=Path, help="OpenHarmony SDK root containing 12/ets, js, native and toolchains")
    parser.add_argument("--modules", required=True, type=Path, help="node_modules containing @ohos/hvigor and @ohos/hvigor-ohos-plugin")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    modules = args.modules.resolve()
    hvigor = modules / "@ohos/hvigor/bin/hvigor.js"
    if not hvigor.is_file() or not (args.sdk / "12/ets/oh-uni-package.json").is_file():
        parser.error("expected Hvigor and the public API 12 SDK")
    env = dict(os.environ, OHOS_BASE_SDK_HOME=str(args.sdk.resolve()))
    with tempfile.TemporaryDirectory(prefix="focus-openharmony-") as temp:
        project = Path(temp)
        for name in ("AppScope", "entry", "hvigor"):
            shutil.copytree(source / name, project / name, ignore=shutil.ignore_patterns("build", "oh_modules", ".hvigor"))
        for name in ("hvigorfile.ts", "oh-package.json5"):
            shutil.copy(source / name, project / name)
        # DevEco may have written local signing configs to the original project.
        # This compiler check uses only unsigned public-SDK target metadata.
        profile = {
            "app": {"products": [{"name": "default", "compileSdkVersion": 12, "compatibleSdkVersion": 12,
                                  "targetSdkVersion": 12, "runtimeOS": "OpenHarmony"}],
                    "buildModeSet": [{"name": "debug"}]},
            "modules": [{"name": "entry", "srcPath": "./entry", "targets": [{"name": "default", "applyToProducts": ["default"]}]}],
        }
        (project / "build-profile.json5").write_text(json.dumps(profile))
        manifest = project / "entry/src/main/module.json5"
        module = json.loads(manifest.read_text())
        module["module"]["deviceTypes"] = ["default"]
        manifest.write_text(json.dumps(module))
        (project / "node_modules").symlink_to(modules, target_is_directory=True)
        subprocess.run(["node", str(hvigor), "--mode", "module", "-p", "product=default", "-p",
                        "module=entry@default", "assembleHap", "--no-daemon"], cwd=project, env=env, check=True)
        built = project / "entry/build/default/outputs/default/entry-default-unsigned.hap"
        with zipfile.ZipFile(built) as hap:
            if hap.testzip() or not hap.getinfo("ets/modules.abc").file_size or not hap.getinfo("module.json").file_size:
                raise RuntimeError("Missing compiled module in HAP")
        output = source / "build/focus-openharmony-api12-unsigned.hap"
        output.parent.mkdir(exist_ok=True)
        shutil.copyfile(built, output)
        print(output)


if __name__ == "__main__":
    main()
