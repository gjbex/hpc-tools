#!/bin/bash -l
#SBATCH --nodes=1 --ntasks-per-node=1 --cpus-per-task=4
#SBATCH --time=01:00:00
#SBATCH --mem=16G

set -euo pipefail

recipe_file=""
container_file=""
labels_file=""
recipe_tmp=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --recipe)
            if [[ -z "${2:-}" || "${2:0:1}" == "-" ]]; then
                echo "Error: Missing value for --recipe"
                exit 1
            fi
            recipe_file="$2"
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
            echo "Usage: $0 --recipe <definition_file> --sif <container_file>"
            echo "Options:"
            echo "  --recipe <definition_file>  Apptainer definition file to build from"
            echo "  --labels <labels_file>      File with %labels entries to append"
            echo "  --sif <container_file>      Name of the output container file"
            echo "  --help                      Show this help message and exit"
            exit 0
            ;;
        *)
            echo "Error: Unknown option '$1'"
            exit 1
            ;;
    esac
done

if [[ -z "${recipe_file:-}" || -z "${container_file:-}" ]]; then
    echo "Error: --recipe and --sif options are required."
    exit 1
fi

if [[ ! -f "$recipe_file" ]]; then
    echo "Error: Recipe file '$recipe_file' does not exist."
    exit 1
fi

if [[ -f "$container_file" ]]; then
    echo "Error: Container file '$container_file' already exists."
    exit 1
fi

if [[ -n "${labels_file:-}" && ! -f "$labels_file" ]]; then
    echo "Error: Labels file '$labels_file' does not exist."
    exit 1
fi

recipe_to_build="$recipe_file"
if [[ -n "${labels_file:-}" ]]; then
    recipe_tmp=$(mktemp --suffix=.def)
    cp "$recipe_file" "$recipe_tmp"
    {
        printf '\n%%labels\n'
        cat "$labels_file"
    } >> "$recipe_tmp"
    recipe_to_build="$recipe_tmp"
fi

cleanup() {
    if [[ -n "${recipe_tmp:-}" && -f "$recipe_tmp" ]]; then
        rm -f "$recipe_tmp"
    fi
}
trap cleanup EXIT

if [[ -n "${VSC_SCRATCH_NODE:-}" ]]; then
    if [[ ! -d "$VSC_SCRATCH_NODE" ]]; then
        echo "Error: VSC_SCRATCH_NODE directory '$VSC_SCRATCH_NODE' does not exist."
        exit 1
    fi
    export APPTAINER_TMPDIR="$VSC_SCRATCH_NODE/$USER/apptainer_tmp"
    mkdir -p "$APPTAINER_TMPDIR"
fi
if [[ -n "${VSC_SCRATCH:-}" ]]; then
    if [[ ! -d "$VSC_SCRATCH" ]]; then
        echo "Error: VSC_SCRATCH directory '$VSC_SCRATCH' does not exist."
        exit 1
    fi
    export APPTAINER_CACHEDIR="$VSC_SCRATCH/apptainer_cache"
    mkdir -p "$APPTAINER_CACHEDIR"
fi

apptainer build \
    --fakeroot \
    "$container_file" \
    "$recipe_to_build"
