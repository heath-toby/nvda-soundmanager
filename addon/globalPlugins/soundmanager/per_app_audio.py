"""
Per-app audio output routing on Windows 10 (1709+) / Windows 11.

Mirrors what the Sound Settings "App volume and device preferences" page does.
Ported from the maintained C# implementation in Belphemur/SoundSwitch:
  https://github.com/Belphemur/SoundSwitch/blob/dev/SoundSwitch.Audio.Manager/
    Interop/Client/Extended/AudioPolicyConfig.cs

Key facts (these are why naive comtypes approaches fail):
  * Factory is obtained via AudioSes.dll!DllGetActivationFactory with the
    runtime class string "Windows.Media.Internal.AudioPolicyConfig" --
    NOT RoGetActivationFactory and NOT CoCreateInstance.
  * IInspectable::GetIids returns several IIDs; the LAST one is the actual
    IAudioPolicyConfig interface for the current Windows build.
  * After QueryInterface to that last IID, the vtable slots we need are:
        25 = SetPersistedDefaultAudioEndpoint(pid, flow, role, HSTRING)
        26 = GetPersistedDefaultAudioEndpoint(pid, flow, role, HSTRING*)
        27 = ClearAllPersistedApplicationDefaultEndpoints()
  * Known valid IIDs (for sanity-check only):
        Pre-1H2:           {2a59116d-6c4f-45e0-a74f-707e3fef9258}
        Windows 10 1709:   {32aa8e18-6496-4e24-9f94-b800e7eccc45}
        Win11 21H2 / 22H2: {ab3d4648-e242-459f-b02f-541c70306324}

Device IDs accepted by set_app_output() are plain MMDevice IDs of the form
"{0.0.0.00000000}.{<guid>}" (what IMMDevice::GetId returns).  Internally
these get wrapped in the SWD#MMDEVAPI# / device-interface-class suffix that
the policy API actually expects -- see _wrap_device_id and EarTrumpet's
DataModel/WindowsAudio/Internal/AudioPolicyConfigService.cs.
"""
import sys
import ctypes
from ctypes import (
    wintypes, POINTER, c_void_p, c_uint32, c_int, byref, WINFUNCTYPE,
)

# Device ID wrapping (from EarTrumpet AudioPolicyConfigService.cs)
_MMDEVAPI_TOKEN = "\\\\?\\SWD#MMDEVAPI#"
_DEVINTERFACE_AUDIO_RENDER = "#{e6327cad-dcec-4949-ae8a-991e976a79d2}"
_DEVINTERFACE_AUDIO_CAPTURE = "#{2eef81be-33fa-4800-9670-1cd474972c3f}"


def _wrap_device_id(device_id, flow):
    if not device_id:
        return ""
    if device_id.startswith(_MMDEVAPI_TOKEN):
        return device_id  # already wrapped
    suffix = _DEVINTERFACE_AUDIO_CAPTURE if flow == 1 else _DEVINTERFACE_AUDIO_RENDER
    return f"{_MMDEVAPI_TOKEN}{device_id}{suffix}"


def _unwrap_device_id(s):
    if not s:
        return ""
    if s.startswith(_MMDEVAPI_TOKEN):
        s = s[len(_MMDEVAPI_TOKEN):]
    for suf in (_DEVINTERFACE_AUDIO_RENDER, _DEVINTERFACE_AUDIO_CAPTURE):
        if s.endswith(suf):
            s = s[:-len(suf)]
    return s

# ---- combase / WinRT string helpers ---------------------------------------
# DLLs and function prototypes are loaded lazily on first use so that simply
# importing this module does not perturb the COM state of the host process
# (NVDA's pycaw enumeration was inconsistent when AudioSes.dll was loaded
# eagerly at import time).
HSTRING = c_void_p

combase = None
audioses = None
WindowsCreateString = None
WindowsGetStringRawBuffer = None
WindowsDeleteString = None
_RoInitialize = None
DllGetActivationFactory = None


def _bind_dlls():
    global combase, audioses, WindowsCreateString, WindowsGetStringRawBuffer
    global WindowsDeleteString, _RoInitialize, DllGetActivationFactory
    if combase is not None:
        return
    combase = ctypes.WinDLL("combase")
    WindowsCreateString = combase.WindowsCreateString
    WindowsCreateString.argtypes = [wintypes.LPCWSTR, c_uint32, POINTER(HSTRING)]
    WindowsCreateString.restype = ctypes.HRESULT
    WindowsGetStringRawBuffer = combase.WindowsGetStringRawBuffer
    WindowsGetStringRawBuffer.argtypes = [HSTRING, POINTER(c_uint32)]
    WindowsGetStringRawBuffer.restype = wintypes.LPCWSTR
    WindowsDeleteString = combase.WindowsDeleteString
    WindowsDeleteString.argtypes = [HSTRING]
    WindowsDeleteString.restype = ctypes.HRESULT
    # RO_INIT_MULTITHREADED = 1. Use c_int32 (not ctypes.HRESULT) so a non-zero
    # return doesn't auto-raise — we need to accept RPC_E_CHANGED_MODE silently
    # when COM is already initialised on this thread (NVDA's main thread is STA).
    _RoInitialize = combase.RoInitialize
    _RoInitialize.argtypes = [c_uint32]
    _RoInitialize.restype = ctypes.c_int32
    audioses = ctypes.WinDLL("AudioSes")
    DllGetActivationFactory = audioses.DllGetActivationFactory
    DllGetActivationFactory.argtypes = [HSTRING, POINTER(c_void_p)]
    DllGetActivationFactory.restype = ctypes.HRESULT


def _ensure_apartment():
    _bind_dlls()
    hr = _RoInitialize(1) & 0xFFFFFFFF
    # S_OK=0, S_FALSE=1 (already init'd same mode), RPC_E_CHANGED_MODE=0x80010106
    # (already init'd different mode — fine, the existing apartment is still valid).
    if hr & 0x80000000 and hr != 0x80010106:
        raise OSError(f"RoInitialize failed: 0x{hr:08X}")


def _hstring(s):
    h = HSTRING()
    hr = WindowsCreateString(s, len(s), byref(h))
    if hr & 0x80000000:
        raise OSError(f"WindowsCreateString failed: 0x{hr & 0xFFFFFFFF:08X}")
    return h


# ---- IInspectable / IUnknown raw vtable prototypes ------------------------
# IUnknown:    0=QueryInterface 1=AddRef 2=Release
# IInspectable:3=GetIids 4=GetRuntimeClassName 5=GetTrustLevel
_QueryInterface = WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_void_p, POINTER(c_void_p))
_Release = WINFUNCTYPE(c_uint32, c_void_p)
_GetIids = WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(c_uint32), POINTER(c_void_p))

# Interface vtable slots (post-QueryInterface).  We use plain c_int32 instead
# of ctypes.HRESULT so PROCESS_NO_AUDIO (0x80070057) doesn't auto-raise --
# the caller checks the HR explicitly.
_Set = WINFUNCTYPE(ctypes.c_int32, c_void_p, c_uint32, c_uint32, c_uint32, HSTRING)
_Get = WINFUNCTYPE(ctypes.c_int32, c_void_p, c_uint32, c_uint32, c_uint32, POINTER(HSTRING))
_Clear = WINFUNCTYPE(ctypes.c_int32, c_void_p)


def _vtbl_slot(obj_ptr, slot):
    vtbl = ctypes.cast(obj_ptr, POINTER(POINTER(c_void_p)))[0]
    return vtbl[slot]


class AudioPolicyConfig:
    """Lazily-initialised holder for the queried IAudioPolicyConfig pointer."""

    _known_iids = {
        b"\x6d\x11\x59\x2a\x4f\x6c\xe0\x45\xa7\x4f\x70\x7e\x3f\xef\x92\x58",
        b"\x18\x8e\xaa\x32\x96\x64\x24\x4e\x9f\x94\xb8\x00\xe7\xec\xcc\x45",
        b"\x48\x46\x3d\xab\x42\xe2\x9f\x45\xb0\x2f\x54\x1c\x70\x30\x63\x24",
    }

    def __init__(self):
        _ensure_apartment()
        # 1. Get the IInspectable activation factory from AudioSes.dll
        name = _hstring("Windows.Media.Internal.AudioPolicyConfig")
        try:
            factory = c_void_p()
            hr = DllGetActivationFactory(name, byref(factory))
            if hr & 0x80000000:
                raise OSError(f"DllGetActivationFactory failed: 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            WindowsDeleteString(name)

        # 2. Call IInspectable::GetIids (vtable slot 3) to discover the
        #    real interface IID for this Windows build. The last one wins.
        get_iids = _GetIids(_vtbl_slot(factory, 3))
        count = c_uint32()
        iids_array = c_void_p()
        hr = get_iids(factory, byref(count), byref(iids_array))
        if hr & 0x80000000:
            raise OSError(f"GetIids failed: 0x{hr & 0xFFFFFFFF:08X}")
        if count.value == 0:
            raise OSError("GetIids returned zero IIDs")

        # Each GUID is 16 bytes; last one is at offset (count-1) * 16
        last_iid_addr = iids_array.value + (count.value - 1) * 16
        iid_bytes = bytes(
            (ctypes.c_ubyte * 16).from_address(last_iid_addr))
        # CoTaskMemFree for the IID array
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoTaskMemFree(iids_array)

        if iid_bytes not in self._known_iids:
            # Not fatal -- log and continue; new builds may add new IIDs.
            sys.stderr.write(
                f"warning: unrecognised IAudioPolicyConfig IID: "
                f"{iid_bytes.hex()}\n")

        # 3. QueryInterface to the per-build interface
        qi = _QueryInterface(_vtbl_slot(factory, 0))
        # Allocate a 16-byte buffer holding the IID and pass its address
        iid_buf = (ctypes.c_ubyte * 16)(*iid_bytes)
        queried = c_void_p()
        hr = qi(factory, ctypes.addressof(iid_buf), byref(queried))
        if hr & 0x80000000:
            raise OSError(f"QueryInterface failed: 0x{hr & 0xFFFFFFFF:08X}")

        # Release the original IInspectable factory; we only need `queried`.
        _Release(_vtbl_slot(factory, 2))(factory)

        self._iface = queried
        self._set = _Set(_vtbl_slot(queried, 25))
        self._get = _Get(_vtbl_slot(queried, 26))
        self._clear = _Clear(_vtbl_slot(queried, 27))
        self._release = _Release(_vtbl_slot(queried, 2))

    def __del__(self):
        try:
            if getattr(self, "_iface", None):
                self._release(self._iface)
        except Exception:
            pass

    def _raw_set(self, pid, flow, role, wrapped):
        h = _hstring(wrapped)
        try:
            hr = self._set(self._iface, pid, flow, role, h)
            # 0x80070057 (E_INVALIDARG) is "PROCESS_NO_AUDIO" -- the override
            # is still persisted and will apply once the process opens an
            # audio session. EarTrumpet/SoundSwitch both ignore this code.
            if hr & 0x80000000 and (hr & 0xFFFFFFFF) != 0x80070057:
                raise OSError(
                    f"SetPersistedDefaultAudioEndpoint(role={role}) failed: "
                    f"0x{hr & 0xFFFFFFFF:08X}")
        finally:
            WindowsDeleteString(h)

    def set_endpoint(self, pid, device_id, flow=0):
        """Set both eConsole and eMultimedia roles (matches EarTrumpet)."""
        wrapped = _wrap_device_id(device_id, flow)
        self._raw_set(pid, flow, 0, wrapped)  # eConsole
        self._raw_set(pid, flow, 1, wrapped)  # eMultimedia

    def get_endpoint(self, pid, flow=0, role=1):
        out = HSTRING()
        hr = self._get(self._iface, pid, flow, role, byref(out))
        try:
            if hr & 0x80000000:
                return None
            length = c_uint32()
            buf = WindowsGetStringRawBuffer(out, byref(length))
            return _unwrap_device_id(buf or "")
        finally:
            WindowsDeleteString(out)

    def clear_all(self):
        hr = self._clear(self._iface)
        if hr & 0x80000000:
            raise OSError(
                f"ClearAllPersistedApplicationDefaultEndpoints failed: 0x{hr & 0xFFFFFFFF:08X}")


# ---- Module-level convenience API ----------------------------------------
_singleton = None


def _get():
    global _singleton
    if _singleton is None:
        _singleton = AudioPolicyConfig()
    return _singleton


def set_app_output(pid, device_id):
    """Route process `pid`'s render audio to MMDevice `device_id`.

    `device_id` should be the IMMDevice::GetId() string, e.g.
    "{0.0.0.00000000}.{<guid>}". Pass "" or None to clear the override.
    Sets both eConsole and eMultimedia roles (matches EarTrumpet behaviour).
    """
    _get().set_endpoint(pid, device_id or "", flow=0)


def clear_app_output(pid):
    set_app_output(pid, "")


def get_app_output(pid):
    return _get().get_endpoint(pid, flow=0, role=1)


def clear_all():
    _get().clear_all()


if __name__ == "__main__":
    import argparse, os
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=os.getpid())
    ap.add_argument("--device", default=None,
                    help='MMDevice ID "{0.0.0.xxx}.{guid}", or "" to clear')
    ap.add_argument("--get", action="store_true")
    ap.add_argument("--clear-all", action="store_true")
    args = ap.parse_args()

    print(f"Windows build: {sys.getwindowsversion().build}")
    if args.clear_all:
        clear_all()
        print("All per-app overrides cleared.")
    elif args.get or args.device is None:
        print(f"PID {args.pid} render endpoint: {get_app_output(args.pid)!r}")
    else:
        set_app_output(args.pid, args.device)
        print(f"PID {args.pid} -> {args.device or '(default)'}")
        print(f"Verify: {get_app_output(args.pid)!r}")
