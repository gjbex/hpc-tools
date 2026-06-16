#!/bin/bash -l
#SBATCH --nodes=1 --ntasks-per-node=1 --cpus-per-task=4
#SBATCH --time=01:00:00
#SBATCH --mem=16G

set -euo pipefail

hpccm_recipe='
# import required modules
import pathlib

# Get the list of apt packages to install
apt_list_filename = USERARG.get("apt_list", "apt_packages.txt")
if not pathlib.Path(apt_list_filename).is_file():
    raise FileNotFoundError(f"File {apt_list_filename} not found.")
with open(apt_list_filename, "r") as apt_file:
    apt_packages = [line.strip() for line in apt_file if line.strip()]

r_package_install_filename = USERARG.get("r_package_install", "install_packages.R")
if not pathlib.Path(r_package_install_filename).is_file():
    raise FileNotFoundError(f"File {r_package_install_filename} not found.")

# Get the base image
image = USERARG.get("baseimage", "ubuntu:22.04")

# Get the bootstrap method
bootstrap = USERARG.get("bootstrap", "docker")
if bootstrap not in ["docker", "localimage"]:
    raise ValueError("Bootstrap method must be either \"docker\" or \"localimage\".")

# If bootstrap is localimage, check that the image file exists
if bootstrap == "localimage" and not pathlib.Path(image).is_file():
    raise FileNotFoundError(f"Local image file {image} does not exist.")

# Get the labels file name
labels_filename = USERARG.get("labels_file", "")

# If labels file is provided, check that it exists and parse it
labels = {}
if labels_filename:
    Stage0 += comment(text=f"Labels file: {labels_filename}")
    if not pathlib.Path(labels_filename).is_file():
        raise FileNotFoundError(f"Labels file {labels_filename} does not exist.")
    with open(labels_filename, "r") as labels_file:
        for line in labels_file:
            line = line.strip()
            if line and not line.startswith("#"):
                key, value = line.split(" ", 1)
                labels[key.strip()] = value.strip()

# Choose a base image
Stage0 += baseimage(image=image, _bootstrap=bootstrap)

# Set permissions of /tmp
Stage0 += shell(commands=["chmod 1777 /tmp"])

# Install apt packages
if apt_packages:
    Stage0 += apt_get(ospackages=apt_packages)

# Add CRAN repository and signature key
if bootstrap == "docker":
    Stage0 += shell(commands=["wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | tee -a /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc"])
    Stage0 += shell(commands=["add-apt-repository \"deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/\""])
    Stage0 += shell(commands=["apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 51716619E084DAB9"])

# Install CMake and compiler suite
if bootstrap == "docker":
    Stage0 += cmake(eula=True)
    Stage0 += gnu()

# Install R
if bootstrap == "docker":
    Stage0 += apt_get(ospackages=[
        "r-base",
        "r-base-dev",
        "r-cran-biocmanager",
    ])

# Install R packages
Stage0 += copy(src=r_package_install_filename, dest="/setup/", _mkdir=True)
Stage0 += shell(commands=[f"Rscript /setup/{r_package_install_filename}"])

# Set environment variables
Stage0 += environment(variables={"LC_ALL": "C.UTF-8"})
Stage0 += environment(variables={"TZ": "Europe/Brussels"})

# Add runtime script
Stage0 += runscript(commands=["Rscript"])

# Add labels to the container if provided
if labels:
    Stage0 += label(metadata=labels)
'

# handle command line arguments
# * --bootstrap <method>: bootstrap method, either 'docker' or 'localimage' (default: 'docker')
# * --baseimage <image>: name of the base image to use (default: 'ubuntu:22.04')
# * --apt <package_list_file>: name of the file that contains the list of apt packages to install (optional if bootstrapping from a local image)
# * --r-install <r-script>: name of the R script that installs R packages (required)
# * --labels <labels_file>: name of the file that contains the labels to add to the container (optional)
# * --sif <container_file>: name of the output container file (default: 'r_container.sif')
# * --help: show a help message and exit
while [[ $# -gt 0 ]]; do
    case $1 in
        --bootstrap)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --bootstrap"
                exit 1
            fi
            bootstrap_method="$2"
            shift 2
            ;;
        --base-image)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --baseimage"
                exit 1
            fi
            base_image="$2"
            shift 2
            ;;
        --apt)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --apt"
                exit 1
            fi
            apt_list_file="$2"
            shift 2
            ;;
        --r-install)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --r-install"
                exit 1
            fi
            r_install_script="$2"
            shift 2
            ;;
        --labels)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --labels"
                exit 1
            fi
            labels_file="$2"
            shift 2
            ;;
        --sif)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --sif"
                exit 1
            fi
            container_file="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 --bootstrap <method> --baseimage <image> --apt <package_list_file> --r-install <r_script>"
            echo "Options:"
            echo "  --bootstrap <method>      Bootstrap method, either 'docker' or 'localimage' (default: 'docker')"
            echo "  --baseimage <image>       Name of the base image to use (default: 'ubuntu:22.04')"
            echo "  --apt <package_list_file> Name of the file that contains the list of apt packages to install (optional if bootstrapping from a local image)"
            echo "  --r-install <r_script>    Name of the R script that installs R packages (required)"
            echo "  --labels <labels_file>    Name of the file that contains labels (optional)"
            echo "  --sif <container_file>    Name of the output container file (required)"
            echo "  --help                    Show this help message and exit"
            exit 0
            ;;
        *)
            echo "Error: Unknown option '$1'"
            exit 1
            ;;
    esac
done

if [[ -z "${container_file:-}" ]]; then
    echo "Error: --sif argument is required."
    exit 1
fi

if [[ -f "$container_file" ]]; then
    echo "Error: Container file '$container_file' already exists. Please remove it or specify a different name."
    exit 1
fi

if [[ -z "${bootstrap_method:-}" ]]; then
    bootstrap_method="docker"
elif [[ "$bootstrap_method" != "docker" && "$bootstrap_method" != "localimage" ]]; then
    echo "Error: --bootstrap must be either 'docker' or 'localimage'."
    exit 1
fi

if [[ "$bootstrap_method" == "localimage" ]]; then
    if [[ -z "${base_image:-}" ]]; then
        echo "Error: --baseimage argument is required when using --bootstrap localimage."
        exit 1
    fi
    if [[ ! -f "$base_image" ]]; then
        echo "Error: Base image file '$base_image' does not exist."
        exit 1
    fi
else
    base_image="ubuntu:22.04"
fi

if [[ "$bootstrap_method" == "docker" ]]; then
    if [[ -z "${apt_list_file:-}" ]]; then
        echo "Error: --apt argument is required when using --bootstrap docker."
        exit 1
    fi
    if [[ ! -f "$apt_list_file" ]]; then
        echo "Error: Apt package list file '$apt_list_file' does not exist."
        exit 1
    fi
else
    apt_list_file=""
fi

if [[ "$bootstrap_method" == "localimage" && -z "${apt_list_file:-}" ]]; then
    apt_list_file=$(mktemp)
    echo "No apt packages to install, using an empty file: $apt_list_file"
fi

if [[ -z "${r_install_script:-}" ]]; then
    echo "Error: --r-install argument is required."
    exit 1
fi
if [[ ! -f "$r_install_script" ]]; then
    echo "Error: R install script '$r_install_script' does not exist."
    exit 1
fi

if [[ -n "${labels_file:-}" && ! -f "$labels_file" ]]; then
    echo "Error: Labels file '$labels_file' does not exist."
    exit 1
fi

echo "Creating python environment and install hpccm..."
venv_dir=$(mktemp -d)
if [[ ! -d "$venv_dir" ]]; then
    echo "Error: Failed to create temporary directory for Python venv."
    exit 1
fi
python3 -m venv "$venv_dir"
source "$venv_dir/bin/activate"
pip install --quiet hpccm

recipe=$(mktemp)
if [[ ! -f "$recipe" ]]; then
    echo "Error: Failed to create temporary file for the recipe."
    exit 1
fi
python <<EOF > "$recipe"
${hpccm_recipe}
EOF

hpccm --recipe "$recipe" \
    --outfile "$container_file" \
    --build-arg apt_list="${apt_list_file:-}" \
    --build-arg r_package_install="${r_install_script}" \
    --build-arg baseimage="${base_image}" \
    --build-arg bootstrap="${bootstrap_method}" \
    --build-arg labels_file="${labels_file:-}"
