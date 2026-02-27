# vmt -- Visual VM Testing

vmt is a visual testing tool for Wayland applications. It spins up ephemeral
QEMU/libvirt VMs from cloud images, runs commands over SSH, takes screenshots,
and diffs them against reference images using SSIM. Designed for both automated
CI pipelines and interactive testing sessions with Claude.

## Quick Start

Install host dependencies (Arch Linux):

```sh
sudo pacman -S libvirt qemu-full cloud-image-utils virt-viewer dnsmasq
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt $USER
```

Clone and install:

```sh
git clone https://github.com/scottstav/vmt.git
cd vmt
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run a VM:

```sh
vmt up arch-sway
vmt ssh arch-sway -- uname -a
vmt view arch-sway
vmt destroy arch-sway
```

## CLI Reference

| Command              | Description                                      |
|----------------------|--------------------------------------------------|
| `up <name>`          | Boot a VM from its manifest                      |
| `destroy <name>`     | Tear down a VM and clean up its working directory |
| `ssh <name> [-- cmd]`| SSH into a VM, or run a single command            |
| `view <name>`        | Open a SPICE viewer for the VM display            |
| `screenshot <name> <remote> <local>` | Take a screenshot and download it |
| `test <name> --manifest <path>`      | Run a test manifest against a VM  |
| `snapshot <name> <snap>`             | Create a libvirt snapshot         |
| `restore <name> <snap>`             | Revert a VM to a snapshot         |
| `update-references <name>`          | Promote current screenshots to references |

Use `-v` / `--verbose` before any subcommand for debug logging.

## VM Manifests

VM configuration uses a two-level system:

- **VM manifests** in `manifests/` define the base VM: cloud image, resources,
  packages, compositor, and SSH settings.
- **Test manifests** in your project define scenarios to run against a VM:
  commands, screenshots, reference images, and thresholds.

### Example VM Manifest

```toml
[vm]
name = "arch-sway"
image = "https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2"
memory = 2048
cpus = 2
disk = 10

[provision]
packages = ["sway", "foot", "grim", "slurp", "pipewire", "wireplumber"]
compositor = "sway"
compositor_cmd = "WLR_BACKENDS=drm sway"
display_server = "wayland"
screenshot_tool = "grim"

[provision.env]
XDG_RUNTIME_DIR = "/run/user/1000"
WLR_RENDERER = "pixman"
WLR_LIBINPUT_NO_DEVICES = "1"

[ssh]
user = "arch"
port = 22
```

### Starter Manifests

| Manifest         | Compositor | Base Image    | Memory |
|------------------|------------|---------------|--------|
| `arch-sway`      | Sway       | Arch Linux    | 2 GB   |
| `fedora-gnome`   | GNOME      | Fedora 41     | 3 GB   |
| `alpine-weston`  | Weston     | Alpine 3.21   | 1 GB   |

## Screenshot Comparison

vmt compares screenshots against reference images using structural similarity
(SSIM) from scikit-image. A score of 1.0 means identical; the default pass
threshold is 0.95.

When a comparison fails, vmt generates a visual diff image highlighting changed
regions in red, making it straightforward to see what shifted.

The threshold is configurable per test scenario in the test manifest.

## Claude Integration

vmt is designed to work with Claude as an interactive QA agent. Boot a VM, run
commands, take screenshots, and use Claude's multimodal vision to verify the
result:

```sh
vmt up arch-sway
vmt ssh arch-sway -- "foot &"
vmt screenshot arch-sway /tmp/shot.png ./shot.png
# Use Claude's Read tool on ./shot.png to visually inspect the result
```

For batch testing, write a test manifest and run:

```sh
vmt test arch-sway --manifest tests/my-app.toml
```

## Host Requirements

- **OS:** Arch Linux (other distros may work with equivalent packages)
- **Packages:** libvirt, qemu-full, cloud-image-utils, virt-viewer, dnsmasq
- **Kernel:** KVM support (`/dev/kvm` must exist)
- **Services:** libvirtd running (`systemctl enable --now libvirtd`)
- **User:** Must be in the `libvirt` group
- **Python:** 3.11+

## License

MIT -- see [LICENSE](LICENSE).
