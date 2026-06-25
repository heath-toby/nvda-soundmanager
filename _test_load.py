"""Test harness: load the soundmanager addon's __init__.py using NVDA's bundled
libraries (pycaw, psutil, comtypes), with NVDA-specific modules stubbed.

Run with NVDA's Python version (3.13). Confirms the addon's imports resolve and
the GlobalPlugin class can be instantiated end-to-end."""
import os
import sys
import types

NVDA_DIR = r"C:\Program Files\NVDA"
NVDA_LIB = os.path.join(NVDA_DIR, "library.zip")

# Point at NVDA's bundled libs and native .pyd files (psutil._psutil_windows.pyd is in NVDA_DIR).
sys.path.insert(0, NVDA_LIB)
sys.path.insert(0, NVDA_DIR)


def stub_module(name, **attrs):
	mod = types.ModuleType(name)
	for k, v in attrs.items():
		setattr(mod, k, v)
	sys.modules[name] = mod
	return mod


# Stub NVDA-internal modules with just enough surface for class definition.
class _GlobalPlugin:
	scriptCategory = ""
	__gestures = {}
	def __init__(self, *a, **kw):
		pass
	def bindGesture(self, *a, **kw):
		pass
	def bindGestures(self, *a, **kw):
		pass
	def clearGestureBindings(self):
		pass


stub_module("globalPluginHandler", GlobalPlugin=_GlobalPlugin)
stub_module("addonHandler", initTranslation=lambda: None)
stub_module("api", getFocusObject=lambda: None)
stub_module("speech", cancelSpeech=lambda: None)
stub_module("tones", beep=lambda f, d: None)
_captured_messages = []
stub_module("ui", message=lambda m: _captured_messages.append(m))


class _PostNotify:
	def register(self, *a, **kw): pass
	def notify(self, *a, **kw): pass


_conf = {"soundManager": {"sayVolumeChange": True, "sayAppChange": True}}


class _Conf:
	spec = {}
	def __getitem__(self, k): return _conf[k]
	def __setitem__(self, k, v): _conf[k] = v


stub_module(
	"config",
	conf=_Conf(),
	post_configProfileSwitch=_PostNotify(),
)


# wx is real but heavy — stub the bits used at class scope.
class _CheckBox:
	def __init__(self, *a, **kw): pass
	def SetValue(self, v): pass
	def IsChecked(self): return True


stub_module("wx", CheckBox=_CheckBox)


# gui has settingsDialogs.NVDASettingsDialog.categoryClasses and SettingsPanel + guiHelper.
class _NVDASettingsDialog:
	categoryClasses = []


class _SettingsPanel:
	pass


class _BoxSizerHelper:
	def __init__(self, *a, **kw): pass
	def addItem(self, item): return item


gui_mod = stub_module("gui")
gui_mod.SettingsPanel = _SettingsPanel
gui_mod.guiHelper = types.SimpleNamespace(BoxSizerHelper=_BoxSizerHelper)
gui_mod.settingsDialogs = types.SimpleNamespace(NVDASettingsDialog=_NVDASettingsDialog)


# Translation gettext — _() is injected by initTranslation; stub it as identity.
import builtins
builtins._ = lambda s: s


# Now load the addon's __init__.py.
addon_init = os.path.join(
	os.path.dirname(os.path.abspath(__file__)),
	"addon", "globalPlugins", "soundmanager", "__init__.py",
)

print(f"Loading {addon_init} ...")
import importlib.util
spec = importlib.util.spec_from_file_location("soundmanager_addon", addon_init)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("  module imported successfully")

print("\nVerifying pycaw resolved to NVDA's bundle:")
import pycaw
print(f"  pycaw.__file__: {pycaw.__file__}")

print("\nVerifying AudioUtilities is callable:")
print(f"  {mod.AudioUtilities}")

print("\nInstantiating GlobalPlugin (this will hit real Core Audio):")
gp = mod.GlobalPlugin()
print(f"  master_volume.name = {gp.master_volume.name!r}")
print(f"  curAppName = {gp.curAppName!r}")
print(f"  enabled = {gp.enabled!r}")

print("\nEnumerating audio sessions (psutil.Process must work):")
sessions = mod.AudioUtilities.GetAllSessions()
print(f"  found {len(sessions)} sessions")
shown = 0
for s in sessions:
	if s.Process is not None and shown < 5:
		print(f"  - {s.Process.name()}")
		shown += 1

print("\nSimulating soundManager toggle script (should beep 660Hz silently):")
gp.script_soundManager(None)
print(f"  enabled after toggle: {gp.enabled!r}")

print("\nTesting up/down announcement (should be bare percentage):")
gp.master_volume.SetMasterVolume = lambda level, ctx: None
gp.master_volume.GetMasterVolume = lambda: 0.84
_captured_messages.clear()
gp.curAppName = gp.master_volume.name
gp.script_volumeUp(None)
print(f"  master-volume up: {_captured_messages!r}  (expected: ['86%'])")

print("\nTesting left/right cycle announcement (should be 'App: Volume N'):")
_captured_messages.clear()
gp.cycleThroughApps(True)
print(f"  cycle forward:    {_captured_messages!r}")

print("\nTesting cycle wrap-around with synthetic duplicate sessions:")
# Substitute a deterministic GetAllSessions that includes duplicate exe names.
class _FakeProc:
	def __init__(self, name): self._n = name
	def name(self): return self._n


class _SAV:
	def GetMasterVolume(self): return 0.5


class _FakeSess:
	def __init__(self, name):
		self.Process = _FakeProc(name)
		self.SimpleAudioVolume = _SAV()


fake_sessions = [
	_FakeSess("chrome.exe"),
	_FakeSess("chrome.exe"),  # duplicate
	_FakeSess("vlc.exe"),
	_FakeSess("chrome.exe"),  # another duplicate
	_FakeSess("spotify.exe"),
]
mod.AudioUtilities.GetAllSessions = lambda: fake_sessions

# Expected dedup'd order: master, chrome, vlc, spotify
gp.curAppName = "Master volume"
expected_forward = ["chrome.exe", "vlc.exe", "spotify.exe", "Master volume", "chrome.exe"]
got = []
for _ in expected_forward:
	gp.cycleThroughApps(True)
	got.append(gp.curAppName)
print(f"  forward wrap: {got}")
assert got == expected_forward, f"forward cycle broken: {got}"

gp.curAppName = "Master volume"
expected_backward = ["spotify.exe", "vlc.exe", "chrome.exe", "Master volume", "spotify.exe"]
got = []
for _ in expected_backward:
	gp.cycleThroughApps(False)
	got.append(gp.curAppName)
print(f"  backward wrap: {got}")
assert got == expected_backward, f"backward cycle broken: {got}"

# Verify oscillation doesn't get stuck on duplicates.
gp.curAppName = "chrome.exe"
gp.cycleThroughApps(False)
left_of_chrome = gp.curAppName
gp.cycleThroughApps(True)
back_to_chrome = gp.curAppName
print(f"  chrome -> left = {left_of_chrome!r}, then right = {back_to_chrome!r}")
assert back_to_chrome == "chrome.exe", "should land back on chrome, not a duplicate"

print("\nAll checks passed.")
