"""Own the dashboard process tree, including short-lived quota collectors."""
import ctypes
from ctypes import wintypes


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
        ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
        ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
        ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', ctypes.c_uint64 * 6),
        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


def kernel():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    return api


def own_tree(child):
    api = kernel()
    job = api.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not api.AssignProcessToJobObject(job, int(child._handle)):
        error = ctypes.get_last_error()
        api.CloseHandle(job)
        raise ctypes.WinError(error)
    return job


def close_tree(job):
    if job:
        kernel().CloseHandle(job)


def resume_child(child):
    """Resume the initial thread only after the suspended child belongs to its job."""
    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
            ('thread_id', wintypes.DWORD), ('process_id', wintypes.DWORD),
            ('base_priority', wintypes.LONG), ('delta_priority', wintypes.LONG),
            ('flags', wintypes.DWORD)]
    api = kernel()
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    api.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenThread.restype = wintypes.HANDLE
    api.ResumeThread.argtypes = [wintypes.HANDLE]
    api.ResumeThread.restype = wintypes.DWORD
    snapshot = api.CreateToolhelp32Snapshot(4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        found = api.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.process_id == child.pid:
                thread = api.OpenThread(2, False, entry.thread_id)
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if api.ResumeThread(thread) == 0xffffffff:
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
                finally:
                    api.CloseHandle(thread)
            found = api.Thread32Next(snapshot, ctypes.byref(entry))
        raise OSError('Suspended dashboard thread not found')
    finally:
        api.CloseHandle(snapshot)
