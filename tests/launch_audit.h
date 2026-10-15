#pragma once

// Test harness only. This file is never included in a competition submission.
// Wrap the actual CANN 9.0 launch API, rather than counting source launch sites.
#ifdef ROPE_LAUNCH_AUDIT
static uint64_t ropeActualKernelLaunches = 0;
extern "C" aclError __real_aclrtLaunchKernelWithHostArgs(
    aclrtFuncHandle, uint32_t, aclrtStream, aclrtLaunchKernelCfg*, void*, size_t,
    aclrtPlaceHolderInfo*, size_t);

extern "C" aclError __wrap_aclrtLaunchKernelWithHostArgs(
    aclrtFuncHandle function, uint32_t blocks, aclrtStream stream,
    aclrtLaunchKernelCfg* config, void* args, size_t argsSize,
    aclrtPlaceHolderInfo* placeholders, size_t placeholderCount) {
    ++ropeActualKernelLaunches;
    return __real_aclrtLaunchKernelWithHostArgs(function, blocks, stream, config,
        args, argsSize, placeholders, placeholderCount);
}
#endif
