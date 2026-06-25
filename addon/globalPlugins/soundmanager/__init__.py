# *-* coding: utf-8 *-*
# Sound Manager
#addon/globalPlugins/sound-manager/__init__.py
#A part of the NVDA Sound Manager add-on
#Copyright (C) 2019 Yannick PLASSIARD, Danstiv, Beqa Gozalishvili
#This file is covered by the GNU General Public License.
#See the file LICENSE for more details.
#
#This addon uses the following dependencies:
# pycaw - see the pycaw.LICENSE file for more details.

import os

# NVDA core requirements
import globalPluginHandler
import addonHandler
import api
import speech
import tones
import ui
import wx
import config
import gui
from logHandler import log

# pycaw is bundled with NVDA (verified in NVDA 2024.1+).
from pycaw.utils import AudioUtilities
from pycaw.constants import AudioDeviceState, EDataFlow

from . import per_app_audio

addonHandler.initTranslation()

# Tones for sub-menu entry / exit.
_MENU_ENTER_TONE_HZ = 1760
_MENU_EXIT_TONE_HZ = 880

# Configuration specifications and default section name.
SM_CFG_SECTION = "soundManager"

confspec = {
	"sayVolumeChange": "boolean(default=true)",
	"sayAppChange": "boolean(default=true)",
}
config.conf.spec[SM_CFG_SECTION] = confspec

# message contexts
SM_CTX_ERROR = 1
SM_CTX_APP_CHANGE = 2
SM_CTX_VOLUME_CHANGE = 3

# A fake Process class with mininal implementation to comply to the cycleThroughApps plugin method.

class MasterVolumeFakeProcess(object):
	def __init__(self, name):
		self._name = name
	def name(self):
		return self._name

#
# Main global plugin class
#


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	# Translators: The name of the add-on presented to the user.
	scriptCategory = _("Sound Manager")
	volumeChangeStep = 0.02
	enabled = False
	curAppName = None
	# Sub-menu state (None when not in a sub-menu).
	_menu = None


	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.readConfiguration()
		self.master_volume = AudioUtilities.GetSpeakers().EndpointVolume
		self.master_volume.SetMasterVolume = self.master_volume.SetMasterVolumeLevelScalar
		self.master_volume.GetMasterVolume = self.master_volume.GetMasterVolumeLevelScalar
		self.master_volume.name = _('Master volume')
		self.master_volume.Process = MasterVolumeFakeProcess(self.master_volume.name)
		self.master_volume.getDisplayName = lambda: self.master_volume.name
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(SoundManagerPanel)
		if hasattr(config, "post_configProfileSwitch"):
			config.post_configProfileSwitch.register(self.handleConfigProfileSwitch)
		else:
			config.configProfileSwitched.register(self.handleConfigProfileSwitch)
	def handleConfigProfileSwitch(self):
		self.readConfiguration()
	def readConfiguration(self):
		self.sayAppChange = config.conf[SM_CFG_SECTION]["sayAppChange"]
		self.sayVolumeChange = config.conf[SM_CFG_SECTION]["sayVolumeChange"]

	def message(self, ctx, msg, interrupt=False):
		if ctx == SM_CTX_VOLUME_CHANGE and self.sayVolumeChange:
			speech.cancelSpeech() if interrupt else None
			ui.message(msg)
		elif ctx == SM_CTX_APP_CHANGE and self.sayAppChange:
			speech.cancelSpeech() if interrupt else None
			ui.message(msg)
		elif ctx == SM_CTX_ERROR:
			ui.message(msg)
		return

	def getAppNameFromSession(self, session):
		"""Returns an application's name formatted to be presented to the user from a given audio session."""

		name = None
		if session is None:
			return self.master_volume.name
		try:
			name = session.getDisplayName()
		except Exception as e:
			name = session.Process.name().replace(".exe", "")
		return name


	def script_muteApp(self, gesture):
		session,volume = self.findSessionByName(self.curAppName)
		if session is None:
			if self.curAppName != self.master_volume.name:
				# Translators: Spoken message when unablee to change audio volume for the given application.
				self.message(SM_CTX_ERROR, _("Unable to retrieve current application."))
				return
			else:
				# Translators: Cannot mute the master volume.
				self.message(SM_CTX_ERROR, _("Cannot mute the master volume."))
				return

		muted = volume.GetMute()
		volume.SetMute(not muted, None)
		if not muted:
			# Translator: Spoken message indicating that the app's sound is now muted.
			self.message(SM_CTX_VOLUME_CHANGE, _("{app} muted").format(app=self.getAppNameFromSession(session)))
		else:
			# Translators: Spoken message indicating that the app's audio is now unmuted.
			self.message(SM_CTX_VOLUME_CHANGE, _("{app} unmuted").format(app=self.getAppNameFromSession(session)))

	def focusCurrentApplication(self, silent=False):
		obj = api.getFocusObject()
		appName = None
		try:
			appName = obj.appModule.appName
		except AttributeError:
			appName = None
		session,volume = self.findSessionByName(appName)
		if session is None:
			if not silent:
				# Translators: The current application does not pay audio.
				self.message(SM_CTX_ERROR, _("{app} is not playing any sound.".format(app=appName)))
			return False
		self.curAppName = appName
		return True

	def script_curAppVolumeUp(self, gesture):
		"""Increases the volume of focused application if it plays audio."""
		if self.focusCurrentApplication() is False:
			return
		self.changeVolume(self.volumeChangeStep)

	def script_curAppVolumeDown(self, gesture):
		"""Decreases the currently focused application's volume."""
		if self.focusCurrentApplication() is False:
			return
		self.changeVolume(-self.volumeChangeStep)

	def script_curAppMute(self, gesture):
		if self.focusCurrentApplication() is False:
			return
		self.script_muteApp(gesture)

	def script_volumeUp(self, gesture):
		"""Increases the volume of the selected application."""
		self.changeVolume(self.volumeChangeStep)
	def script_volumeDown(self, gesture):
		"""Decreases the volume of the selected application."""
		self.changeVolume(-self.volumeChangeStep)

	def changeVolume(self, volumeStep):
		session,volume = self.findSessionByName(self.curAppName)
		selector = self.master_volume
		if volume is None and self.curAppName is not None:
			# Translators: Spoken message when unablee to change audio volume for the given application
			self.message(SM_CTX_ERROR, _("Unable to retrieve current application."))
			return
		newVolume = volume.GetMasterVolume() + volumeStep
		if volumeStep > 0 and newVolume > 1:
			newVolume = 1.0
		elif volumeStep < 0 and newVolume < 0:
			newVolume = 0.0

		volume.SetMasterVolume(newVolume, None)
		# Translators: Message indicating the volume's percentage ("95%").
		self.message(SM_CTX_VOLUME_CHANGE, _("{volume}%").format(volume=int(round(newVolume * 100))), True)

	def cycleThroughApps(self, goForward):
		# Dedupe by exe name: the addon identifies sessions by Process.name(), so two
		# sessions sharing a name (e.g. multiple chrome.exe PIDs) collapse into one entry.
		# Without this, the cycle could oscillate between duplicates and feel "stuck".
		sessions = [self.master_volume]
		seen = {self.master_volume.Process.name()}
		for s in AudioUtilities.GetAllSessions():
			if s.Process is None:
				continue
			name = s.Process.name()
			if name in seen:
				continue
			seen.add(name)
			sessions.append(s)
		curIdx = next((i for i, s in enumerate(sessions) if s.Process.name() == self.curAppName), None)
		if curIdx is None:
			newSession = sessions[0]
		else:
			step = 1 if goForward else -1
			newSession = sessions[(curIdx + step) % len(sessions)]
		self.curAppName = newSession.Process.name()
		if newSession is self.master_volume:
			vol = newSession.GetMasterVolume()
		else:
			vol = newSession.SimpleAudioVolume.GetMasterVolume()
		# Translators: Announced when cycling to a different app in layered mode, e.g. "VLC: Volume 86".
		self.message(SM_CTX_APP_CHANGE, _("{app}: Volume {volume}").format(
			app=self.getAppNameFromSession(newSession),
			volume=int(round(vol * 100)),
		))

	def script_nextApp(self, gesture):
		self.cycleThroughApps(True)

	def script_previousApp(self, gesture):
		self.cycleThroughApps(False)

	def _bindLayeredGestures(self):
		self.bindGesture("kb:escape", "soundManager")
		self.bindGesture("kb:control+uparrow", "curAppVolumeUp")
		self.bindGesture("kb:control+downarrow", "curAppVolumeDown")
		self.bindGesture("kb:control+m", "curAppMute")
		self.bindGesture("kb:uparrow", "volumeUp")
		self.bindGesture("kb:downarrow", "volumeDown")
		self.bindGesture("kb:leftarrow", "previousApp")
		self.bindGesture("kb:rightarrow", "nextApp")
		self.bindGesture("kb:m", "muteApp")
		self.bindGesture("kb:d", "defaultDeviceMenu")
		self.bindGesture("kb:o", "appOutputMenu")

	def script_soundManager(self, gesture):
		self.enabled = not self.enabled
		if self.enabled is True:
			tones.beep(660, 100)
			self._bindLayeredGestures()
			if not self.focusCurrentApplication(True):
				self.curAppName = self.master_volume.name

		else:
			tones.beep(440, 100)
			self.clearGestureBindings()
			self.bindGestures(self.__gestures)

	# Translators: Main script help message.
	script_soundManager.__doc__ = _("""Toggle volume control adjustment on or off""")

	# --- Output device sub-menus (D and O keys) ----------------------------

	def _listOutputDevices(self):
		"""Return [(device_id, friendly_name)] for active render endpoints,
		with the current system default first."""
		try:
			default_id = AudioUtilities.GetSpeakers().id
		except Exception:
			default_id = None
		devs = []
		try:
			for d in AudioUtilities.GetAllDevices():
				try:
					if d.state != AudioDeviceState.Active:
						continue
					flow = AudioUtilities.GetEndpointDataFlow(d.id)
					# pycaw returns either the EDataFlow enum or the bare name string
					# depending on Windows version; accept both.
					if flow != EDataFlow.eRender and not str(flow).endswith("eRender"):
						continue
					name = d.FriendlyName or _("(unnamed device)")
					devs.append((d.id, name))
				except Exception:
					continue
		except Exception as e:
			log.error("Sound Manager: device enumeration failed: %r", e)
		devs.sort(key=lambda x: x[0] != default_id)
		return devs

	def _findPidsForApp(self, app_name):
		"""Return the list of PIDs whose audio session matches app_name."""
		pids = []
		try:
			for s in AudioUtilities.GetAllSessions():
				if s.Process is not None and s.Process.name() == app_name:
					pids.append(s.Process.pid)
		except Exception:
			pass
		return pids

	def _previewSelection(self, device_id):
		"""Route NVDA's own audio to device_id so the next speech goes through it.
		Pass an empty string to clear the override (fall back to system default)."""
		try:
			per_app_audio.set_app_output(os.getpid(), device_id or "")
		except Exception as e:
			log.warning("Sound Manager: NVDA preview routing failed: %r", e)

	def _enterMenu(self, kind, target_pids=None, target_label=None):
		devices = self._listOutputDevices()
		if not devices:
			self.message(SM_CTX_ERROR, _("No active output devices found."))
			return
		items = list(devices)
		if kind == "output":
			# Translators: Top entry in the per-app output menu — clears the override.
			items.insert(0, (None, _("Default")))
		# Save state for revert
		try:
			orig_default = AudioUtilities.GetSpeakers().id
		except Exception:
			orig_default = None
		orig_app_route = ""
		if kind == "output" and target_pids:
			try:
				orig_app_route = per_app_audio.get_app_output(target_pids[0]) or ""
			except Exception:
				orig_app_route = ""
		try:
			orig_nvda_route = per_app_audio.get_app_output(os.getpid()) or ""
		except Exception:
			orig_nvda_route = ""
		# Start index: match the device currently in effect
		if kind == "default":
			start_idx = next((i for i, (did, _n) in enumerate(items) if did == orig_default), 0)
		else:
			if not orig_app_route:
				start_idx = 0  # "Default"
			else:
				start_idx = next((i for i, (did, _n) in enumerate(items) if did == orig_app_route), 0)
		self._menu = {
			"kind": kind,
			"target_pids": target_pids or [],
			"target_label": target_label,
			"items": items,
			"index": start_idx,
			"orig_default": orig_default,
			"orig_app_route": orig_app_route,
			"orig_nvda_route": orig_nvda_route,
		}
		# Swap key bindings: sub-menu only listens to arrows / enter / escape.
		self.clearGestureBindings()
		self.bindGesture("kb:upArrow", "menuPrev")
		self.bindGesture("kb:downArrow", "menuNext")
		self.bindGesture("kb:enter", "menuCommit")
		self.bindGesture("kb:numpadEnter", "menuCommit")
		self.bindGesture("kb:escape", "menuCancel")
		tones.beep(_MENU_ENTER_TONE_HZ, 100)
		# Speak intro then the current selection (with preview routing).
		if kind == "default":
			intro = _("Default output device")
		else:
			intro = _("Output for {app}").format(app=target_label or "")
		ui.message(intro)
		self._previewAndAnnounceCurrent()

	def _previewAndAnnounceCurrent(self):
		if not self._menu:
			return
		device_id, name = self._menu["items"][self._menu["index"]]
		# Route NVDA's own process so speech comes through the candidate device.
		# For the "Default" entry (device_id is None) we clear NVDA's override
		# so it follows the current system default.
		self._previewSelection(device_id or "")
		speech.cancelSpeech()
		ui.message(name)

	def _exitMenu(self, committed):
		if not self._menu:
			return
		menu = self._menu
		self._menu = None  # mark exit early so re-entrancy is safe
		# Revert NVDA's own preview routing first.
		try:
			per_app_audio.set_app_output(os.getpid(), menu["orig_nvda_route"])
		except Exception as e:
			log.warning("Sound Manager: revert NVDA routing failed: %r", e)
		device_id, name = menu["items"][menu["index"]]
		if committed:
			if menu["kind"] == "default":
				try:
					AudioUtilities.SetDefaultDevice(device_id)
				except Exception as e:
					log.error("Sound Manager: SetDefaultDevice failed: %r", e)
			else:
				# Per-app routing — apply to every PID matching the app name.
				route_to = device_id or ""
				for pid in menu["target_pids"]:
					try:
						per_app_audio.set_app_output(pid, route_to)
					except Exception as e:
						log.error("Sound Manager: set_app_output failed for pid %s: %r", pid, e)
			# Translators: Confirmation after saving an output device choice.
			msg = _("Saved: {name}").format(name=name)
		else:
			# Translators: Confirmation after cancelling an output device menu.
			msg = _("Cancelled")
		tones.beep(_MENU_EXIT_TONE_HZ, 100)
		speech.cancelSpeech()
		ui.message(msg)
		# Restore the main layered bindings.
		self.clearGestureBindings()
		self._bindLayeredGestures()

	def script_defaultDeviceMenu(self, gesture):
		"""Open the default-output-device selection menu."""
		self._enterMenu("default")

	def script_appOutputMenu(self, gesture):
		"""Open the per-app output-device selection menu for the currently selected app."""
		if not self.curAppName or self.curAppName == self.master_volume.name:
			self.message(SM_CTX_ERROR, _("Select an app first."))
			return
		pids = self._findPidsForApp(self.curAppName)
		if not pids:
			self.message(SM_CTX_ERROR, _("No audio session found for {app}.").format(app=self.curAppName))
			return
		label = self.curAppName.replace(".exe", "")
		self._enterMenu("output", target_pids=pids, target_label=label)

	def script_menuPrev(self, gesture):
		if not self._menu:
			return
		self._menu["index"] = (self._menu["index"] - 1) % len(self._menu["items"])
		self._previewAndAnnounceCurrent()

	def script_menuNext(self, gesture):
		if not self._menu:
			return
		self._menu["index"] = (self._menu["index"] + 1) % len(self._menu["items"])
		self._previewAndAnnounceCurrent()

	def script_menuCommit(self, gesture):
		self._exitMenu(committed=True)

	def script_menuCancel(self, gesture):
		self._exitMenu(committed=False)

	def findSessionByName(self, name):
		if name == self.master_volume.name:
			return None,self.master_volume
		sessions = AudioUtilities.GetAllSessions()
		for session in sessions:
			if session.Process is not None:
				pName = session.Process.name()
				if name is None or name.lower() in pName.lower():
					volume = session.SimpleAudioVolume
					return session,volume
		return None,None

	__gestures = {
		"kb:nvda+shift+v": "soundManager",
	}
# The next class has been adapted from the ScreenCurtain module.


class SoundManagerPanel(gui.SettingsPanel):
	# Translators: This is the label for the Sound manager settings panel.
	title = _("Sound Manager")

	def makeSettings(self, settingsSizer):
		sHelper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.smSayVolumeChange = sHelper.addItem(wx.CheckBox(self, label=_("&announce volume changes")))
		self.smSayVolumeChange.SetValue(config.conf[SM_CFG_SECTION]["sayVolumeChange"])

		self.smSayAppChange = sHelper.addItem(wx.CheckBox(self, label=_("Announce a&pp names when cycling")))
		self.smSayAppChange.SetValue(config.conf[SM_CFG_SECTION]["sayAppChange"])

	def onSave(self):
		config.conf[SM_CFG_SECTION]["sayVolumeChange"] = self.smSayVolumeChange.IsChecked()
		config.conf[SM_CFG_SECTION]["sayAppChange"] = self.smSayAppChange.IsChecked()
		if hasattr(config, "post_configProfileSwitch"):
			config.post_configProfileSwitch.notify()
		else:
			config.configProfileSwitched.notify()
