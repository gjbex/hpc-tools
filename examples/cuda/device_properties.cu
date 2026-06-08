#include <cuda_runtime.h>

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

void check(cudaError_t status, const char *call) {
    if (status != cudaSuccess) {
        std::cerr << call << " failed: " << cudaGetErrorString(status) << '\n';
        std::exit(EXIT_FAILURE);
    }
}

double mib(size_t bytes) {
    return static_cast<double>(bytes) / (1024.0 * 1024.0);
}

double gib(size_t bytes) {
    return static_cast<double>(bytes) / (1024.0 * 1024.0 * 1024.0);
}

void print_bytes(const std::string &label, size_t bytes) {
    std::cout << "  " << std::left << std::setw(42) << label << ": "
              << std::right << bytes << " bytes"
              << " (" << std::fixed << std::setprecision(2) << mib(bytes)
              << " MiB, " << gib(bytes) << " GiB)\n";
}

void print_int(const std::string &label, int value) {
    std::cout << "  " << std::left << std::setw(42) << label << ": "
              << std::right << value << '\n';
}

void print_dim3(const std::string &label, const int values[3]) {
    std::cout << "  " << std::left << std::setw(42) << label << ": "
              << std::right << values[0] << " x " << values[1] << " x "
              << values[2] << '\n';
}

void print_attr(int device, cudaDeviceAttr attr, const std::string &label) {
    int value = 0;
    cudaError_t status = cudaDeviceGetAttribute(&value, attr, device);
    if (status == cudaSuccess) {
        print_int(label, value);
        return;
    }

    std::cout << "  " << std::left << std::setw(42) << label << ": "
              << "unavailable (" << cudaGetErrorString(status) << ")\n";
    cudaGetLastError();
}

void print_attr_bytes(int device, cudaDeviceAttr attr, const std::string &label) {
    int value = 0;
    cudaError_t status = cudaDeviceGetAttribute(&value, attr, device);
    if (status == cudaSuccess) {
        print_bytes(label, static_cast<size_t>(value));
        return;
    }

    std::cout << "  " << std::left << std::setw(42) << label << ": "
              << "unavailable (" << cudaGetErrorString(status) << ")\n";
    cudaGetLastError();
}

void print_device(int device) {
    cudaDeviceProp prop{};
    check(cudaGetDeviceProperties(&prop, device), "cudaGetDeviceProperties");

    std::cout << "Device " << device << ": " << prop.name << '\n';
    print_int("compute capability major", prop.major);
    print_int("compute capability minor", prop.minor);
    print_int("multiprocessor count", prop.multiProcessorCount);
    print_int("warp size", prop.warpSize);

    print_bytes("total global memory", prop.totalGlobalMem);
    print_bytes("shared memory per block", prop.sharedMemPerBlock);
    print_bytes("shared memory per multiprocessor", prop.sharedMemPerMultiprocessor);
    print_bytes("total constant memory", prop.totalConstMem);
    print_bytes("L2 cache", static_cast<size_t>(prop.l2CacheSize));

    print_int("registers per block", prop.regsPerBlock);
    print_int("registers per multiprocessor", prop.regsPerMultiprocessor);
    print_int("memory clock rate kHz", prop.memoryClockRate);
    print_int("memory bus width bits", prop.memoryBusWidth);

    if (prop.memoryClockRate > 0 && prop.memoryBusWidth > 0) {
        double gb_per_second =
            2.0 * static_cast<double>(prop.memoryClockRate) * 1000.0 *
            static_cast<double>(prop.memoryBusWidth) / 8.0 / 1.0e9;
        std::cout << "  " << std::left << std::setw(42)
                  << "theoretical memory bandwidth"
                  << ": " << std::right << std::fixed << std::setprecision(2)
                  << gb_per_second << " GB/s\n";
    }

    print_bytes("persisting L2 cache max size", prop.persistingL2CacheMaxSize);

#if CUDART_VERSION >= 11000
    print_bytes("opt-in shared memory per block", prop.sharedMemPerBlockOptin);
#endif

    std::cout << "  Launch limits\n";
    print_int("max threads per block", prop.maxThreadsPerBlock);
    print_dim3("max block dimensions", prop.maxThreadsDim);
    print_dim3("max grid dimensions", prop.maxGridSize);
    print_int("max threads per multiprocessor", prop.maxThreadsPerMultiProcessor);
#if CUDART_VERSION >= 12000
    print_int("max blocks per multiprocessor", prop.maxBlocksPerMultiProcessor);
#endif

    std::cout << "  Attribute cross-checks\n";
    print_attr_bytes(device, cudaDevAttrL2CacheSize, "attribute L2 cache");
    print_attr_bytes(device, cudaDevAttrMaxPersistingL2CacheSize,
                     "attribute persisting L2 max size");
    print_attr_bytes(device, cudaDevAttrMaxSharedMemoryPerBlock,
                     "attribute shared memory per block");
    print_attr_bytes(device, cudaDevAttrMaxSharedMemoryPerMultiprocessor,
                     "attribute shared memory per SM");
#if CUDART_VERSION >= 11000
    print_attr_bytes(device, cudaDevAttrMaxSharedMemoryPerBlockOptin,
                     "attribute opt-in shared memory/block");
#endif
    print_attr(device, cudaDevAttrMaxRegistersPerBlock,
               "attribute registers per block");
    print_attr(device, cudaDevAttrMaxRegistersPerMultiprocessor,
               "attribute registers per SM");
    print_attr(device, cudaDevAttrMaxThreadsPerMultiProcessor,
               "attribute max threads per SM");
    print_attr(device, cudaDevAttrMaxBlocksPerMultiprocessor,
               "attribute max blocks per SM");
    print_attr(device, cudaDevAttrMemoryClockRate,
               "attribute memory clock kHz");
    print_attr(device, cudaDevAttrGlobalMemoryBusWidth,
               "attribute memory bus width bits");

    std::cout << '\n';
}

} // namespace

int main() {
    int runtime_version = 0;
    int driver_version = 0;
    check(cudaRuntimeGetVersion(&runtime_version), "cudaRuntimeGetVersion");
    check(cudaDriverGetVersion(&driver_version), "cudaDriverGetVersion");

    int count = 0;
    check(cudaGetDeviceCount(&count), "cudaGetDeviceCount");

    std::cout << "CUDA runtime version: " << runtime_version << '\n';
    std::cout << "CUDA driver version:  " << driver_version << '\n';
    std::cout << "Visible CUDA devices: " << count << "\n\n";

    for (int device = 0; device < count; ++device) {
        print_device(device);
    }

    return EXIT_SUCCESS;
}
