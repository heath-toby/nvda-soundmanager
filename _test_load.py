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


_conf = {"soundManager": {"sayVolumeChange": True, "sayAppChange": True, "volumeStepPercent": 1}}


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


class _SpinCtrl:
	def __init__(self, *a, **kw):
		self._v = kw.get("initial", 1)
	def GetValue(self): return self._v


stub_module("wx", CheckBox=_CheckBox, SpinCtrl=_SpinCtrl)


# gui has settingsDialogs.NVDASettingsDialog.categoryClasses and SettingsPanel + guiHelper.
class _NVDASettingsDialog:
	categoryClasses = []


class _SettingsPanel:
	pass


class _BoxSizerHelper:
	def __init__(self, *a, **kw): pass
	def addItem(self, item): return item
	def addLabeledControl(self, label, klass, **kw): return klass(**kw)


gui_mod = stub_module("gui")
gui_mod.SettingsPanel = _SettingsPanel
gui_mod.guiHelper = types.SimpleNamespace(BoxSizerHelper=_BoxSizerHelper)
gui_mod.settingsDialogs = types.SimpleNamespace(NVDASettingsDialog=_NVDASettingsDialog)


# Translation gettext — _() is injected by initTranslation; stub it as identity.
import builtins
builtins._ = lambda s: s


# Load the addon as a proper package so relative imports resolve.
# NVDA's globalPlugins/ is a namespace package; the simplest mirror here is to
# put the parent of the soundmanager package directly on sys.path.
pkg_parent = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addon", "globalPlugins")
sys.path.insert(0, pkg_parent)
print(f"Loading soundmanager from {pkg_parent!r}")
import importlib
mod = importlib.import_module("soundmanager")
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
expected_pct = int(round(0.84 * 100 + gp.volumeChangeStep * 100))
print(f"  master-volume up: {_captured_messages!r}  (expected: ['{expected_pct}%'])")

print("\nTesting left/right cycle announcement (should be 'App: Volume N'):")
_captured_messages.clear()
gp.cycleThroughApps(True)
print(f"  cycle forward:    {_captured_messages!r}")

print("\nTesting cycle wrap-around with synthetic duplicate sessions:")
_orig_GetAllSessions = mod.AudioUtilities.GetAllSessions
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

print("\nTesting D menu (default device selection):")
# Restore the real impl that the cycle test replaced.
mod.AudioUtilities.GetAllSessions = _orig_GetAllSessions
# Open the default-device menu
_captured_messages.clear()
gp.script_defaultDeviceMenu(None)
assert gp._menu is not None, "menu should be open"
print(f"  intro+first: {_captured_messages!r}")
print(f"  device count in menu: {len(gp._menu['items'])}")
print(f"  starting index: {gp._menu['index']}")
# Arrow down twice
_captured_messages.clear()
gp.script_menuNext(None)
gp.script_menuNext(None)
print(f"  after 2x next: {_captured_messages!r}")
print(f"  index now: {gp._menu['index']}")
# Cancel
_captured_messages.clear()
gp.script_menuCancel(None)
assert gp._menu is None, "menu should be closed after cancel"
print(f"  after cancel: {_captured_messages!r}  (expected 'Cancelled')")

print("\nTesting O menu (per-app output) — for a real session:")
real_sessions_again = list(_orig_GetAllSessions())
print(f"  real sessions visible: {[s.Process.name() for s in real_sessions_again if s.Process is not None]}")
target_session = next((s for s in real_sessions_again if s.Process is not None), None)
if target_session:
	gp.curAppName = target_session.Process.name()
	print(f"  curAppName = {gp.curAppName!r}")
	print(f"  _findPidsForApp returns: {gp._findPidsForApp(gp.curAppName)!r}")
	_captured_messages.clear()
	gp.script_appOutputMenu(None)
	assert gp._menu is not None, "O menu should open"
	# Expected items: Default + active render devices
	print(f"  items: {[name for _id, name in gp._menu['items']]}")
	assert gp._menu['items'][0][0] is None, "top item should be the 'Default' clear-override entry"
	print(f"  intro+current: {_captured_messages!r}")
	_captured_messages.clear()
	gp.script_menuCancel(None)
	assert gp._menu is None
	print(f"  after cancel: {_captured_messages!r}")

print("\nAll checks passed.")
