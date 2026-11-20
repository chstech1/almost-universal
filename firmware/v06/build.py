"""Build an offline FR5086D ARM development image with LLVM and FreqChip's SDK."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
LOCAL_SDK = HERE.parents[2] / "analysis/universal-remote/v46-custom-fw/sdk/fr5080-6b8777c.tar.gz"
SDK_SHA = "84e8063b7516163554afca611167fc311dbdb9fcf1f951e965cadb1a1a72ccac"

def tool(name):
    path = shutil.which(name)
    if not path:
        path = "/opt/homebrew/opt/llvm@20/bin/" + name
    if not Path(path).is_file() and name == "ld.lld" and shutil.which("rustc"):
        root = Path(subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip())
        path = next(root.glob("lib/rustlib/*/bin/gcc-ld/ld.lld"), path)
    if not Path(path).is_file():
        raise SystemExit(f"Install LLVM and put {name} on PATH")
    return str(path)

def run(args):
    subprocess.run(args, check=True)

def vectors(sdk, dest):
    """Translate the SDK's vector table and two Thumb exception veneers to GNU syntax."""
    path = sdk / "components/modules/platform/src/app_boot_vectors.s"
    source = path.read_text(encoding="latin-1")
    words = re.findall(r"^\s*DCD\s+(\w+)", source, re.M)
    assert len(words) == 48 and words[0] == "__initial_sp"
    lines = [".syntax unified", ".thumb", '.section .vectors,"a"', ".word 0x40004000"]
    lines.extend(".word " + word for word in words[1:])
    lines.append('.section .text.handlers,"ax"')
    for name in ("HardFault_Handler_Ram","SVC_Handler"):
        lines.extend([".thumb_func",name+":"])
        body = re.search(r"^"+name+r"\s+PROC(.*?)ENDP",source,re.S|re.M)[1]
        for line in body.splitlines():
            line=line.split(";")[0].strip()
            if not line or line.startswith("IMPORT"): continue
            if line in ("SVC_Handler_1","SVC_Handler_2"): line+=":"
            lines.append(line.replace("{LR, R3}","{R3, LR}"))
    for name in re.findall(r"EXPORT\s+(\w+)\s+\[WEAK\]",source):
        lines.extend([".weak "+name,".thumb_func",name+":","b ."])
    dest.write_text("\n".join(lines)+"\n")

def build(sdk, out, tmp, smoke):
    comp=sdk/"components"
    for name in ("type_lib.h","pskeys.h"):
        header=(comp/"btdm/include"/name).read_text(encoding="latin-1")
        (tmp/name).write_text(re.sub(r"__packed\s+struct", "struct __attribute__((packed))",header))
    includes=[tmp,HERE/"port", HERE, comp/"btdm/include", comp/"driver/include",
              comp/"modules/os", comp/"modules/platform/include", comp/"modules/common/api",
              comp/"modules/aes/api"]
    flags=["--target=arm-none-eabi","-mcpu=cortex-m3","-mthumb","-mfloat-abi=soft",
           "-ffreestanding","-fshort-enums","-ffunction-sections","-fdata-sections","-Oz",
           "-D__ARMCC_VERSION=5060422","-D__forceinline=inline","-D__irq="]
    flags += ["-I"+str(i) for i in includes]
    objs=[]
    def compile_file(src, vendor=False):
        obj=tmp/(src.stem+".o")
        warn=["-w"] if vendor else ["-Wall","-Wextra","-Werror"]
        run([tool("clang"),*flags,*warn,"-c",src,"-o",obj])
        objs.append(obj)
    for name in ("remote","keys","display","board","peripheral","platform"):
        compile_file(HERE/(name+".c"))
    for name in ("driver_syscntl","driver_gpio","driver_pmu","driver_uart","driver_ipc"):
        compile_file(comp/"driver"/(name+".c"),True)
    compile_file(comp/"modules/platform/src/hardfault.c",True)
    vec=tmp/"vectors.S"
    vectors(sdk,vec)
    compile_file(vec)
    lib=comp/"btdm/library/5080_host.lib"
    # Keil writes a private absolute metadata symbol after global symbols.
    # Normalize that non-loadable metadata for the LLVM linker.
    original=lib
    lib=tmp/"host.a"
    run([tool("llvm-objcopy"),"--wildcard","--strip-symbol=BuildAttributes*",
         "--remove-section=.ARM.attributes","--strip-debug",original,lib])
    symbols=(comp/"btdm/library/syscall.txt").read_text(encoding="latin-1")
    lines=[]
    for addr, kind, sym in re.findall(r"^(0x\w+) ([TD]) ([\w$]+)\s*$",symbols,re.M):
        lines.append(f'PROVIDE("{sym}" = {addr});')
    for er,section,part in (("ER_BOOT",".vectors",""),("ER_RE_RAM",".ramcode",""),
                            ("ER_RW",".data","RW$$"),("ER_ZI",".bss","ZI$$"),
                            ("TIME_SEC",".time",""),("DATE_SEC",".date","")):
        for partname,op in (("Load","LOADADDR"),("Image","ADDR")):
            for end,add in (("Base",""),("Limit","+SIZEOF("+section+")")):
                lines.append(f'"{partname}$${er}$${part}{end}" = {op}({section}){add};')
    syms=tmp/"sdk.ld"
    syms.write_text("\n".join(lines)+"\n")
    out.mkdir(parents=True, exist_ok=True)
    elf=out/"v06-menu.elf"
    run([tool("ld.lld"),"--gc-sections","--error-limit=40","-T",HERE/"fr5080.ld","-T",syms,
         *objs,lib,"-Map="+str(out/"v06-menu.map"),"-o",elf])
    run([tool("llvm-objcopy"),"-O","binary",elf,out/"ARM.bin"])
    if smoke:
        for name in ("smoke", "qemu-test"):
            compile_file(HERE/"tests"/(name+".c"))
        fixture=tmp/"smoke.elf"
        keep={"remote","keys","peripheral","smoke","qemu-test"}
        run([tool("ld.lld"),"-T",HERE/"tests/qemu-test.ld","-o",fixture,
             *[obj for obj in objs if obj.stem in keep]])
        subprocess.run([tool("qemu-system-arm"),"-M","mps2-an385","-cpu","cortex-m3",
                        "-display","none","-serial","none","-monitor","none",
                        "-semihosting-config","enable=on,target=native","-kernel",fixture],
                       check=True,timeout=30)
    print("ARM.bin",hashlib.sha256((out/"ARM.bin").read_bytes()).hexdigest(),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk",type=Path,default=LOCAL_SDK,help="pinned SDK archive or extracted fr5080 directory")
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--smoke",action="store_true",help="run the Cortex-M3 GATT integration test")
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        tmp=Path(folder)
        sdk=args.sdk.resolve()
        if sdk.is_file():
            if hashlib.sha256(sdk.read_bytes()).hexdigest()!=SDK_SHA:
                raise SystemExit("Unrecognized SDK archive")
            with tarfile.open(sdk) as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    relative=Path(member.name)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise SystemExit("Unexpected SDK archive path")
                    target=tmp/relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("wb") as dest:
                        shutil.copyfileobj(source,dest)
            sdk=tmp/"fr5080"
        build(sdk,args.out.resolve(),tmp,args.smoke)
