from enigma import eTimer, eDVBResourceManager, eDVBDiseqcCommand, eDVBFrontendParametersSatellite, iDVBFrontend

from time import sleep
from operator import mul as mul
from random import SystemRandom as SystemRandom
from threading import Thread as Thread
from threading import Event as Event

from enigma import eTimer, eDVBSatelliteEquipmentControl, eDVBResourceManager, eDVBDiseqcCommand, eDVBFrontendParametersSatellite, iDVBFrontend

from Components.ActionMap import NumberActionMap, ActionMap
from Components.Button import Button
from Components.config import config, ConfigSatlist, ConfigNothing, ConfigSelection, ConfigSubsection, ConfigInteger, ConfigFloat, KEY_LEFT, KEY_RIGHT, KEY_0, getConfigListEntry, NoSave
from Components.ConfigList import ConfigList
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.MenuList import MenuList
from Components.NimManager import nimmanager
from Components.ScrollLabel import ScrollLabel
from Components.Pixmap import Pixmap
from Components.Sources.StaticText import StaticText
from Components.TunerInfo import TunerInfo
from Components.TuneTest import Tuner
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.InfoBar import InfoBar
from Screens.MessageBox import MessageBox
from Screens.Satconfig import NimSetup
from Screens.Screen import Screen
from Tools.Transponder import ConvertToHumanReadable
from Tools.Hex2strColor import Hex2strColor
from skin import parameters


from . import log
from . import rotor_calc


class PositionerSetup(Screen):

	@staticmethod
	def satposition2metric(position):
		if position > 1800:
			position = 3600 - position
			orientation = "west"
		else:
			orientation = "east"
		return (position, orientation)

	@staticmethod
	def orbital2metric(position, orientation):
		if orientation == "west":
			position = 360 - position
		if orientation == "south":
			position = - position
		return position

	@staticmethod
	def longitude2orbital(position):
		if position >= 180:
			return 360 - position, "west"
		else:
			return position, "east"

	@staticmethod
	def latitude2orbital(position):
		if position >= 0:
			return position, "north"
		else:
			return -position, "south"

	FIRST_UPDATE_INTERVAL = 500				# milliseconds
	UPDATE_INTERVAL = 50					# milliseconds
	STATUS_MSG_TIMEOUT = 2					# seconds
	LOG_SIZE = 16 * 1024					# log buffer size

	def __init__(self, session, feid):
		self.session = session
		Screen.__init__(self, session)
		self.setTitle(_("Positioner setup"))
		self.feid = feid
		self.oldref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		self.oldref_stop = False
		self.rotor_diseqc = True
		self.frontend = None
		self.rotor_pos = config.usage.showdish.value and config.misc.lastrotorposition.value != 9999
		self.tsid = self.onid = self.orb_pos = 0
		self.checkingTsidOnid = False
		self.finesteps = 0
		getCurrentTuner = None
		getCurrentSat = None
		self.availablesats = []
		log.open(self.LOG_SIZE)
		if config.Nims[self.feid].configMode.value == 'advanced':
			self.advanced = True
			self.advancedconfig = config.Nims[self.feid].advanced
			self.advancedsats = self.advancedconfig.sat
		else:
			self.advanced = False
		self.availablesats = [x[0] for x in nimmanager.getRotorSatListForNim(self.feid)]
		cur = {}
		if not self.openFrontend():
			service = self.session.nav.getCurrentService()
			feInfo = service and service.frontendInfo()
			if feInfo:
				cur_info = feInfo.getTransponderData(True)
				frontendData = feInfo.getAll(True)
				getCurrentTuner = frontendData and frontendData.get("tuner_number", None)
				getCurrentSat = cur_info.get('orbital_position', None)
			del feInfo
			del service
			if self.oldref and getCurrentTuner is not None:
				if self.feid == getCurrentTuner:
					self.oldref_stop = True
				else:
					for n in nimmanager.nim_slots:
						try:
							advanced_satposdepends = n.config_mode == 'advanced' and int(n.config.advanced.sat[3607].lnb.value) != 0
						except:
							advanced_satposdepends = False
						if n.config_mode in ("loopthrough", "satposdepends") or advanced_satposdepends:
							if n.config.connectedTo.value and int(n.config.connectedTo.value) == self.feid:
								self.oldref_stop = True
				if self.oldref_stop:
					self.session.nav.stopService()  # try to disable foreground service
					if getCurrentSat is not None and getCurrentSat in self.availablesats:
						cur = cur_info
					else:
						self.rotor_diseqc = False
			getCurrentTuner = None
			getCurrentSat = None
			if not self.openFrontend():
				if hasattr(session, 'pipshown') and session.pipshown:  # try to disable pip
					service = self.session.pip.pipservice
					feInfo = service and service.frontendInfo()
					if feInfo:
						cur_pip_info = feInfo.getTransponderData(True)
						frontendData = feInfo.getAll(True)
						getCurrentTuner = frontendData and frontendData.get("tuner_number", None)
						getCurrentSat = cur_pip_info.get('orbital_position', None)
						if getCurrentTuner is not None and self.feid == getCurrentTuner:
							if getCurrentSat is not None and getCurrentSat in self.availablesats:
								cur = cur_pip_info
							else:
								self.rotor_diseqc = False
					del feInfo
					del service
					InfoBar.instance and hasattr(InfoBar.instance, "showPiP") and InfoBar.instance.showPiP()
					if hasattr(session, 'pip'):  # try to disable pip again
						del session.pip
						session.pipshown = False
					if not self.openFrontend():
						self.frontend = None  # in normal case this should not happen
						if hasattr(self, 'raw_channel'):
							del self.raw_channel
			if self.frontend is None:
				self.messageTimer = eTimer()
				self.messageTimer.callback.append(self.showMessageBox)
				self.messageTimer.start(2000, True)
		self.frontendStatus = {}
		self.diseqc = Diseqc(self.frontend)
		# True means we dont like that the normal sec stuff sends commands to the rotor!
		self.tuner = Tuner(self.frontend, ignore_rotor=True)

		tp = (cur.get("frequency", 0) // 1000,
			cur.get("symbol_rate", 0) // 1000,
			cur.get("polarization", eDVBFrontendParametersSatellite.Polarisation_Horizontal),
			cur.get("fec_inner", eDVBFrontendParametersSatellite.FEC_Auto),
			cur.get("inversion", eDVBFrontendParametersSatellite.Inversion_Unknown),
			cur.get("orbital_position", 0),
			cur.get("system", eDVBFrontendParametersSatellite.System_DVB_S),
			cur.get("modulation", eDVBFrontendParametersSatellite.Modulation_QPSK),
			cur.get("rolloff", eDVBFrontendParametersSatellite.RollOff_alpha_0_35),
			cur.get("pilot", eDVBFrontendParametersSatellite.Pilot_Unknown),
			cur.get("is_id", eDVBFrontendParametersSatellite.No_Stream_Id_Filter),
			cur.get("pls_mode", eDVBFrontendParametersSatellite.PLS_Gold),
			cur.get("pls_code", eDVBFrontendParametersSatellite.PLS_Default_Gold_Code),
			cur.get("t2mi_plp_id", eDVBFrontendParametersSatellite.No_T2MI_PLP_Id),
			cur.get("t2mi_pid", eDVBFrontendParametersSatellite.T2MI_Default_Pid))

		self.tuner.tune(tp)
		self.isMoving = False
		self.stopOnLock = False

		self.red = Button("")
		self["key_red"] = self.red
		self.green = Button("")
		self["key_green"] = self.green
		self.yellow = Button("")
		self["key_yellow"] = self.yellow
		self.blue = Button("")
		self["key_blue"] = self.blue

		self.list = []
		self["list"] = ConfigList(self.list)

		self["snr_db"] = TunerInfo(TunerInfo.SNR_DB, statusDict=self.frontendStatus)
		self["snr_bar"] = TunerInfo(TunerInfo.SNR_BAR, statusDict=self.frontendStatus)
		self["snr_percentage"] = TunerInfo(TunerInfo.SNR_PERCENTAGE, statusDict=self.frontendStatus)
		self["agc_percentage"] = TunerInfo(TunerInfo.AGC_PERCENTAGE, statusDict=self.frontendStatus)
		self["agc_bar"] = TunerInfo(TunerInfo.AGC_BAR, statusDict=self.frontendStatus)
		self["ber_value"] = TunerInfo(TunerInfo.BER_VALUE, statusDict=self.frontendStatus)
		self["ber_bar"] = TunerInfo(TunerInfo.BER_BAR, statusDict=self.frontendStatus)
		self["lock_state"] = TunerInfo(TunerInfo.LOCK_STATE, statusDict=self.frontendStatus)

		self["rotorstatus"] = Label("")
		self["frequency_value"] = Label("")
		self["symbolrate_value"] = Label("")
		self["fec_value"] = Label("")
		self["status_bar"] = Label("")
		self["SNR"] = Label(_("SNR:"))
		self["BER"] = Label(_("BER:"))
		self["AGC"] = Label(_("AGC:"))
		self["Frequency"] = Label(_("Frequency:"))
		self["Symbolrate"] = Label(_("Symbol rate:"))
		self["FEC"] = Label(_("FEC:"))
		self["Lock"] = Label(_("Lock:"))
		self["lock_off"] = Pixmap()
		self["lock_on"] = Pixmap()
		self["lock_on"].hide()
		if self.rotor_pos:
			if hasattr(eDVBSatelliteEquipmentControl.getInstance(), "getTargetOrbitalPosition"):
				current_pos = eDVBSatelliteEquipmentControl.getInstance().getTargetOrbitalPosition()
				if current_pos in self.availablesats and current_pos != config.misc.lastrotorposition.value:
					config.misc.lastrotorposition.value = current_pos
					config.misc.lastrotorposition.save()
				for x in nimmanager.nim_slots:
					if x.slot == self.feid:
						rotorposition = hasattr(x.config, 'lastsatrotorposition') and x.config.lastsatrotorposition.value or ""
						if rotorposition.isdigit():
							current_pos = int(rotorposition)
							if current_pos != config.misc.lastrotorposition.value:
								config.misc.lastrotorposition.value = current_pos
								config.misc.lastrotorposition.save()
						break
			text = _("Current rotor position: ") + self.OrbToStr(config.misc.lastrotorposition.value)
			self["rotorstatus"].setText(text)
		self.statusMsgTimeoutTicks = 0
		self.statusMsgBlinking = False
		self.statusMsgBlinkCount = 0
		self.statusMsgBlinkRate = 500 // self.UPDATE_INTERVAL  # milliseconds
		self.tuningChangedTo(tp)

		self["actions"] = NumberActionMap(["DirectionActions", "OkCancelActions", "ColorActions", "TimerEditActions", "InputActions", "InfobarMenuActions"],
		{
			"ok": self.keyOK,
			"cancel": self.keyCancel,
			"up": self.keyUp,
			"down": self.keyDown,
			"left": self.keyLeft,
			"right": self.keyRight,
			"red": self.redKey,
			"green": self.greenKey,
			"yellow": self.yellowKey,
			"blue": self.blueKey,
			"log": self.showLog,
			"mainMenu": self.furtherOptions,
			"1": self.keyNumberGlobal,
			"2": self.keyNumberGlobal,
			"3": self.keyNumberGlobal,
			"4": self.keyNumberGlobal,
			"5": self.keyNumberGlobal,
			"6": self.keyNumberGlobal,
			"7": self.keyNumberGlobal,
			"8": self.keyNumberGlobal,
			"9": self.keyNumberGlobal,
			"0": self.keyNumberGlobal
		}, -1)

		self.updateColors("tune")
		self.statusTimer = eTimer()
		self.rotorStatusTimer = eTimer()
		self.statusTimer.callback.append(self.updateStatus)
		self.rotorStatusTimer.callback.append(self.startStatusTimer)
		self.collectingStatistics = False
		self.statusTimer.start(self.FIRST_UPDATE_INTERVAL, True)
		self.dataAvailable = Event()
		self.onClose.append(self.__onClose)
		self.createConfig()
		self.createSetup()

	def __onClose(self):
		self.statusTimer.stop()
		log.close()
		if self.frontend:
			self.frontend = None
		if hasattr(self, 'raw_channel'):
			del self.raw_channel
		self.session.nav.playService(self.oldref)

	def OrbToStr(self, orbpos):
		if orbpos > 1800:
			orbpos = 3600 - orbpos
			return "%d.%d%s W" % (orbpos // 10, orbpos % 10, "\xb0")
		return "%d.%d%s E" % (orbpos // 10, orbpos % 10, "\xb0")

	def setDishOrbosValue(self):
		if self.getRotorMovingState():
			if self.orb_pos != 0 and self.orb_pos != config.misc.lastrotorposition.value:
				config.misc.lastrotorposition.value = self.orb_pos
				config.misc.lastrotorposition.save()
			text = _("Moving to position") + " " + self.OrbToStr(self.orb_pos)
			self.startStatusTimer()
		else:
			text = _("Current rotor position: ") + self.OrbToStr(config.misc.lastrotorposition.value)
		self["rotorstatus"].setText(text)

	def startStatusTimer(self):
		self.rotorStatusTimer.start(1000, True)

	def getRotorMovingState(self):
		return eDVBSatelliteEquipmentControl.getInstance().isRotorMoving()

	def showMessageBox(self):
		text = _("Sorry, this tuner is in use.")
		if self.session.nav.getRecordings():
			text += "\n"
			text += _("Maybe the reason that recording is currently running. Please stop the recording before trying to configure the positioner.")
		self.session.open(MessageBox, text, MessageBox.TYPE_ERROR)

	def restartPrevService(self, yesno):
		if not yesno:
			self.oldref = None
		self.close(None)

	def keyCancel(self):
		if self.oldref is not None:
			if self.oldref_stop:
				self.session.openWithCallback(self.restartPrevService, MessageBox, _("Zap back to service before positioner setup?"), MessageBox.TYPE_YESNO)
			else:
				self.restartPrevService(True)
		else:
			self.restartPrevService(False)

	def openFrontend(self):
		self.frontend = None
		if hasattr(self, 'raw_channel'):
			del self.raw_channel
		res_mgr = eDVBResourceManager.getInstance()
		if res_mgr:
			self.raw_channel = res_mgr.allocateRawChannel(self.feid)
			if self.raw_channel:
				self.frontend = self.raw_channel.getFrontend()
				if self.frontend:
					return True
				else:
					print("getFrontend failed")
			else:
				print("getRawChannel failed")
		else:
			print("getResourceManager instance failed")
		return False

	def setLNB(self, lnb):
		try:
			self.sitelon = lnb.longitude.float
			self.longitudeOrientation = lnb.longitudeOrientation.value
			self.sitelat = lnb.latitude.float
			self.latitudeOrientation = lnb.latitudeOrientation.value
			self.tuningstepsize = lnb.tuningstepsize.float
			self.rotorPositions = lnb.rotorPositions.value
			self.turningspeedH = lnb.turningspeedH.float
			self.turningspeedV = lnb.turningspeedV.float
		except:  # some reasonable defaults from NimManager
			self.sitelon = 5.1
			self.longitudeOrientation = 'east'
			self.sitelat = 50.767
			self.latitudeOrientation = 'north'
			self.tuningstepsize = 0.36
			self.rotorPositions = 99
			self.turningspeedH = 2.3
			self.turningspeedV = 1.7
		self.sitelat = PositionerSetup.orbital2metric(self.sitelat, self.latitudeOrientation)
		self.sitelon = PositionerSetup.orbital2metric(self.sitelon, self.longitudeOrientation)

	def createConfig(self):
		rotorposition = 1
		orb_pos = 0
		self.printMsg(_("Using tuner %s") % chr(0x41 + self.feid))
		if not self.advanced:
			self.printMsg(_("Configuration mode: %s") % _("simple"))
			nim = config.Nims[self.feid]
			self.sitelon = nim.longitude.float
			self.longitudeOrientation = nim.longitudeOrientation.value
			self.sitelat = nim.latitude.float
			self.latitudeOrientation = nim.latitudeOrientation.value
			self.sitelat = PositionerSetup.orbital2metric(self.sitelat, self.latitudeOrientation)
			self.sitelon = PositionerSetup.orbital2metric(self.sitelon, self.longitudeOrientation)
			self.tuningstepsize = nim.tuningstepsize.float
			self.rotorPositions = nim.rotorPositions.value
			self.turningspeedH = nim.turningspeedH.float
			self.turningspeedV = nim.turningspeedV.float
		else:  # it is advanced
			lnb = None
			self.printMsg(_("Configuration mode: %s") % _("advanced"))
			fe_data = {}
			if self.frontend:
				self.frontend.getFrontendData(fe_data)
				self.frontend.getTransponderData(fe_data, True)
				orb_pos = fe_data.get("orbital_position", None)
				if orb_pos is not None and orb_pos in self.availablesats:
					rotorposition = int(self.advancedsats[orb_pos].rotorposition.value)
				lnb = self.getLNBfromConfig(orb_pos)
			self.setLNB(lnb)
		self.positioner_tune = ConfigNothing()
		self.positioner_move = ConfigNothing()
		self.positioner_finemove = ConfigNothing()
		self.positioner_limits = ConfigNothing()
		self.positioner_storage = ConfigInteger(default=rotorposition, limits=(1, self.rotorPositions))
		self.allocatedIndices = []
		m = PositionerSetup.satposition2metric(orb_pos)
		self.orbitalposition = ConfigFloat(default=[int(m[0] // 10), m[0] % 10], limits=[(0, 180), (0, 9)])
		self.orientation = ConfigSelection([("east", _("East")), ("west", _("West"))], default=m[1])
		for x in (self.positioner_tune, self.positioner_storage, self.orbitalposition):
			x.addNotifier(self.retune, initial_call=False)

	def retune(self, configElement):
		self.createSetup()

	def getUsals(self):
		usals = None
		if self.frontend is not None:
			if self.advanced:
				fe_data = {}
				self.frontend.getFrontendData(fe_data)
				self.frontend.getTransponderData(fe_data, True)
				orb_pos = fe_data.get("orbital_position", -9999)
				try:
					pos = str(PositionerSetup.orbital2metric(self.orbitalposition.float, self.orientation.value))
					orb_val = int(pos.replace('.', ''))
				except:
					orb_val = -9999
				sat = -9999
				if orb_val == orb_pos:
					sat = orb_pos
				elif orb_val != -9999 and orb_val in self.availablesats:
					sat = orb_val
				if sat != -9999 and sat in self.availablesats:
					usals = self.advancedsats[sat].usals.value
					self.rotor_diseqc = True
				return usals
			else:
				self.rotor_diseqc = True
				return True
		return usals

	def getLNBfromConfig(self, orb_pos):
		if orb_pos is None or orb_pos == 0:
			return None
		lnb = None
		if orb_pos in self.availablesats:
			lnbnum = int(self.advancedsats[orb_pos].lnb.value)
			if not lnbnum:
				for allsats in range(3601, 3607):
					lnbnum = int(self.advancedsats[allsats].lnb.value)
					if lnbnum:
						break
			if lnbnum:
				self.printMsg(_("Using LNB %d") % lnbnum)
				lnb = self.advancedconfig.lnb[lnbnum]
		if not lnb:
			self.logMsg(_("Warning: no LNB; using factory defaults."), timeout=8)
		return lnb

	def createSetup(self):
		self.list = []
		self.list.append((_("Tune and focus"), self.positioner_tune, "tune"))
		self.list.append((_("Movement"), self.positioner_move, "move"))
		self.list.append((_("Fine movement"), self.positioner_finemove, "finemove"))
		self.list.append((_("Set limits"), self.positioner_limits, "limits"))
		self.list.append((_("Memory index") + (self.getUsals() and " (USALS)" or ""), self.positioner_storage, "storage"))
		self.list.append((_("Goto"), self.orbitalposition, "goto"))
		self.list.append((" ", self.orientation, "goto"))
		self["list"].l.setList(self.list)

	def keyOK(self):
		entry = self.getCurrentConfigPath()
		if entry == "tune":
			self.redKey()
		elif entry == "finemove":
			self.statusMsg(_("Steps") + self.stepCourse(self.finesteps), timeout=self.STATUS_MSG_TIMEOUT)

	def getCurrentConfigPath(self):
		return self["list"].getCurrent()[2]

	def keyUp(self):
		if not self.isMoving:
			self["list"].instance.moveSelection(self["list"].instance.moveUp)
			self.updateColors(self.getCurrentConfigPath())

	def keyDown(self):
		if not self.isMoving:
			self["list"].instance.moveSelection(self["list"].instance.moveDown)
			self.updateColors(self.getCurrentConfigPath())

	def keyNumberGlobal(self, number):
		if self.frontend is None:
			return
		self["list"].handleKey(KEY_0 + number)

	def keyLeft(self):
		if self.frontend is None:
			return
		self["list"].handleKey(KEY_LEFT)

	def keyRight(self):
		if self.frontend is None:
			return
		self["list"].handleKey(KEY_RIGHT)

	def updateColors(self, entry):
		if self.frontend is None:
			return
		if entry == "tune":
			self.red.setText(_("Tune"))
			self.green.setText(_("Auto focus"))
			self.yellow.setText(_("Calibrate"))
			self.blue.setText(_("Calculate"))
		elif entry == "move":
			if self.isMoving:
				self.red.setText(_("Stop"))
				self.green.setText(_("Stop"))
				self.yellow.setText(_("Stop"))
				self.blue.setText(_("Stop"))
			else:
				self.red.setText(_("Move west"))
				self.green.setText(_("Search west"))
				self.yellow.setText(_("Search east"))
				self.blue.setText(_("Move east"))
		elif entry == "finemove":
			self.red.setText("")
			self.green.setText(_("Step west"))
			self.yellow.setText(_("Step east"))
			self.blue.setText("")
		elif entry == "limits":
			self.red.setText(_("Limits off"))
			self.green.setText(_("Limit west"))
			self.yellow.setText(_("Limit east"))
			self.blue.setText(_("Limits on"))
		elif entry == "storage":
			self.red.setText("")
			if self.getUsals() is False:
				self.green.setText(_("Store position"))
				self.yellow.setText(_("Goto position"))
			else:
				self.green.setText("")
				self.yellow.setText("")
			if self.advanced and self.getUsals() is False:
				self.blue.setText(_("Allocate"))
			else:
				self.blue.setText("")
		elif entry == "goto":
			self.red.setText("")
			self.green.setText(_("Goto 0"))
			self.yellow.setText(_("Goto X"))
			self.blue.setText("")
		else:
			self.red.setText("")
			self.green.setText("")
			self.yellow.setText("")
			self.blue.setText("")

	def printMsg(self, msg):
		print(msg)
		print(msg, file=log)

	def stopMoving(self):
		self.printMsg(_("Stop"))
		self.diseqccommand("stop")
		self.isMoving = False
		self.stopOnLock = False
		self.statusMsg(_("Stopped"), timeout=self.STATUS_MSG_TIMEOUT)

	def stepCourse(self, steps):
		def dots(s):
			s = abs(s)
			return (s // 10) * '.' if s < 100 else 10 * '.'

		if steps > 0:
			return 4 * " " + ">| %s %d" % (dots(steps), steps)  # west
		elif steps < 0:
			return 4 * " " + "%d %s |<" % (abs(steps), dots(steps))  # east
		else:
			return 4 * " " + ">|<"

	def redKey(self):
		if self.frontend is None:
			return
		entry = self.getCurrentConfigPath()
		if entry != "finemove":
			self.finesteps = 0
		if entry == "move":
			if self.isMoving:
				self.stopMoving()
			else:
				self.printMsg(_("Move west"))
				self.diseqccommand("moveWest", 0)
				self.isMoving = True
				self.statusMsg(_("Moving west ..."), blinking=True)
			self.updateColors("move")
		elif entry == "limits":
			self.printMsg(_("Limits off"))
			self.diseqccommand("limitOff")
			self.statusMsg(_("Limits cancelled"), timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "tune":
			fe_data = {}
			self.frontend.getFrontendData(fe_data)
			self.frontend.getTransponderData(fe_data, True)
			feparm = self.tuner.lastparm.getDVBS()
			fe_data["orbital_position"] = feparm.orbital_position
			self.statusTimer.stop()
			self.session.openWithCallback(self.tune, TunerScreen, self.feid, fe_data)

	def greenKey(self):
		if self.frontend is None:
			return
		entry = self.getCurrentConfigPath()
		if entry != "finemove":
			self.finesteps = 0
		if entry == "tune":
			# Auto focus
			self.printMsg(_("Auto focus"))
			print((_("Site latitude") + "      : %5.1f %s") % PositionerSetup.latitude2orbital(self.sitelat), file=log)
			print((_("Site longitude") + "     : %5.1f %s") % PositionerSetup.longitude2orbital(self.sitelon), file=log)
			Thread(target=self.autofocus).start()
		elif entry == "move":
			if self.isMoving:
				self.stopMoving()
			else:
				self.printMsg(_("Search west"))
				self.isMoving = True
				self.stopOnLock = True
				self.diseqccommand("moveWest", 0)
				self.statusMsg(_("Searching west ..."), blinking=True)
			self.updateColors("move")
		elif entry == "finemove":
			self.finesteps += 1
			self.printMsg(_("Step west"))
			self.diseqccommand("moveWest", 0xFF)  # one step
			self.statusMsg(_("Stepped west") + self.stepCourse(self.finesteps), timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "storage":
			if self.getUsals() is False:
				menu = [(_("yes"), "yes"), (_("no"), "no")]
				available_orbos = False
				orbos = None
				if self.advanced:
					try:
						orb_pos = str(PositionerSetup.orbital2metric(self.orbitalposition.float, self.orientation.value))
						orbos = int(orb_pos.replace('.', ''))
					except:
						pass
					if orbos is not None and orbos in self.availablesats:
						available_orbos = True
						menu.append((_("Yes (save index in setup tuner)"), "save"))
				index = int(self.positioner_storage.value)
				text = _("Really store at index %2d for current position?") % index

				def saveAction(choice):
					if choice:
						if choice[1] in ("yes", "save"):
							self.printMsg(_("Store at index"))
							self.diseqccommand("store", index)
							self.statusMsg((_("Position stored at index") + " %2d") % index, timeout=self.STATUS_MSG_TIMEOUT)
							if choice[1] == "save" and available_orbos:
								self.advancedsats[orbos].rotorposition.value = index
								self.advancedsats[orbos].rotorposition.save()
				self.session.openWithCallback(saveAction, ChoiceBox, title=text, list=menu)
		elif entry == "limits":
			self.printMsg(_("Limit west"))
			self.diseqccommand("limitWest")
			self.statusMsg(_("West limit set"), timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "goto":
			self.printMsg(_("Goto 0"))
			self.diseqccommand("moveTo", 0)
			self.statusMsg(_("Moved to position 0"), timeout=self.STATUS_MSG_TIMEOUT)

	def yellowKey(self):
		if self.frontend is None:
			return
		entry = self.getCurrentConfigPath()
		if entry != "finemove":
			self.finesteps = 0
		if entry == "move":
			if self.isMoving:
				self.stopMoving()
			else:
				self.printMsg(_("Move east"))
				self.isMoving = True
				self.stopOnLock = True
				self.diseqccommand("moveEast", 0)
				self.statusMsg(_("Searching east ..."), blinking=True)
			self.updateColors("move")
		elif entry == "finemove":
			self.finesteps -= 1
			self.printMsg(_("Step east"))
			self.diseqccommand("moveEast", 0xFF)  # one step
			self.statusMsg(_("Stepped east") + self.stepCourse(self.finesteps), timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "storage":
			if self.getUsals() is False:
				self.printMsg(_("Goto index position"))
				index = int(self.positioner_storage.value)
				self.diseqccommand("moveTo", index)
				self.statusMsg((_("Moved to position at index") + " %2d") % index, timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "limits":
			self.printMsg(_("Limit east"))
			self.diseqccommand("limitEast")
			self.statusMsg(_("East limit set"), timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "goto":
			self.printMsg(_("Move to position X"))
			satlon = self.orbitalposition.float
			position = ("%5.1f %s") % (satlon, self.orientation.value)
			print((_("Satellite longitude:") + " %s") % position, file=log)
			satlon = PositionerSetup.orbital2metric(satlon, self.orientation.value)
			self.statusMsg((_("Moving to position") + " %s") % position, timeout=self.STATUS_MSG_TIMEOUT)
			self.gotoX(satlon)
		elif entry == "tune":
			# Start USALS calibration
			self.printMsg(_("USALS calibration"))
			print((_("Site latitude") + "      : %5.1f %s") % PositionerSetup.latitude2orbital(self.sitelat), file=log)
			print((_("Site longitude") + "     : %5.1f %s") % PositionerSetup.longitude2orbital(self.sitelon), file=log)
			Thread(target=self.gotoXcalibration).start()

	def blueKey(self):
		if self.frontend is None:
			return
		entry = self.getCurrentConfigPath()
		if entry != "finemove":
			self.finesteps = 0
		if entry == "move":
			if self.isMoving:
				self.stopMoving()
			else:
				self.printMsg(_("Move east"))
				self.diseqccommand("moveEast", 0)
				self.isMoving = True
				self.statusMsg(_("Moving east ..."), blinking=True)
			self.updateColors("move")
		elif entry == "limits":
			self.printMsg(_("Limits on"))
			self.diseqccommand("limitOn")
			self.statusMsg(_("Limits enabled"), timeout=self.STATUS_MSG_TIMEOUT)
		elif entry == "tune":
			# Start (re-)calculate
			self.session.openWithCallback(self.recalcConfirmed, MessageBox, _("This will (re-)calculate all positions of your rotor and may remove previously memorised positions and fine-tuning!\nAre you sure?"), MessageBox.TYPE_YESNO, default=False, timeout=10)
		elif entry == "storage":
			if self.advanced and self.getUsals() is False:
				self.printMsg(_("Allocate unused memory index"))
				while True:
					if not len(self.allocatedIndices):
						for sat in self.availablesats:
							usals = self.advancedsats[sat].usals.value
							if not usals:
								current_index = int(self.advancedsats[sat].rotorposition.value)
								if current_index not in self.allocatedIndices:
									self.allocatedIndices.append(current_index)
						if len(self.allocatedIndices) == self.rotorPositions:
							self.statusMsg(_("No free index available"), timeout=self.STATUS_MSG_TIMEOUT)
							break
					index = 1
					for i in sorted(self.allocatedIndices):
						if i != index:
							break
						index += 1
					if index <= self.rotorPositions:
						self.positioner_storage.value = index
						self["list"].invalidateCurrent()
						self.allocatedIndices.append(index)
						self.statusMsg((_("Index allocated:") + " %2d") % index, timeout=self.STATUS_MSG_TIMEOUT)
						break
					else:
						self.allocatedIndices = []

	def recalcConfirmed(self, yesno):
		if yesno:
			self.printMsg(_("Calculate all positions"))
			print((_("Site latitude") + "      : %5.1f %s") % PositionerSetup.latitude2orbital(self.sitelat), file=log)
			print((_("Site longitude") + "     : %5.1f %s") % PositionerSetup.longitude2orbital(self.sitelon), file=log)
			lon = self.sitelon
			if lon >= 180:
				lon -= 360
			if lon < -30:  # americas, make unsigned binary west positive polarity
				lon = -lon
			lon = int(round(lon)) & 0xFF
			lat = int(round(self.sitelat)) & 0xFF
			index = int(self.positioner_storage.value) & 0xFF
			self.diseqccommand("calc", (((index << 8) | lon) << 8) | lat)
			self.statusMsg(_("Calculation complete"), timeout=self.STATUS_MSG_TIMEOUT)

	def showLog(self):
		self.session.open(PositionerSetupLog)

	def diseqccommand(self, cmd, param=0):
		print("Diseqc(%s, %X)" % (cmd, param), file=log)
		self["rotorstatus"].setText("")
		self.diseqc.command(cmd, param)
		self.tuner.retune()

	def tune(self, transponder):
		# re-start the update timer
		self.statusTimer.start(self.UPDATE_INTERVAL, True)
		self.createSetup()
		if transponder is not None:
			self.tuner.tune(transponder)
			self.tuningChangedTo(transponder)
		feparm = self.tuner.lastparm.getDVBS()
		orb_pos = feparm.orbital_position
		m = PositionerSetup.satposition2metric(orb_pos)
		self.orbitalposition.value = [int(m[0] // 10), m[0] % 10]
		self.orientation.value = m[1]
		if self.advanced:
			if orb_pos in self.availablesats:
				rotorposition = int(self.advancedsats[orb_pos].rotorposition.value)
				self.positioner_storage.value = rotorposition
				self.allocatedIndices = []
			self.setLNB(self.getLNBfromConfig(orb_pos))

	def furtherOptions(self):
		menu = []
		text = _("Select action")
		if self.session.nav.getCurrentlyPlayingServiceOrGroup() and not self.oldref_stop:
			menu.append((_("Stop live TV service"), self.stopService))
		description = _("Open setup tuner ") + "%s" % chr(0x41 + self.feid)
		menu.append((description, self.openTunerSetup))
		if not self.checkingTsidOnid and self.frontend and self.isLocked() and not self.isMoving:
			menu.append((_("Checking ONID/TSID"), self.openONIDTSIDScreen))

		def openAction(choice):
			if choice:
				choice[1]()
		self.session.openWithCallback(openAction, ChoiceBox, title=text, list=menu)

	def stopService(self):
		self.oldref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		self.session.nav.stopService()
		self.oldref_stop = True

	def openTunerSetup(self):
		self.session.openWithCallback(self.closeTunerSetup, NimSetup, self.feid)

	def openONIDTSIDScreen(self):
		self.tsid = self.onid = 0
		self.session.openWithCallback(self.startChecktsidonid, ONIDTSIDScreen)

	def startChecktsidonid(self, tsidonid=None):
		if tsidonid is not None:
			self.onid = tsidonid[0]
			self.tsid = tsidonid[1]
			if self.frontend and self.isLocked() and not self.isMoving and hasattr(self, "raw_channel") and self.raw_channel:
				self.checkingTsidOnid = True
				self.raw_channel.receivedTsidOnid.get().append(self.gotTsidOnid)
				self.raw_channel.requestTsidOnid()

	def gotTsidOnid(self, tsid, onid):
		colors = parameters.get("PositionerOnidTsidcolors", (0x0000FF00, 0x00FF0000))  # "valid", "not valid"
		if tsid == self.tsid and onid == self.onid:
			msg = Hex2strColor(colors[0]) + _("This valid ONID/TSID")
		else:
			msg = Hex2strColor(colors[1]) + _("This not valid ONID/TSID")
		self.statusMsg(msg, blinking=True, timeout=10)
		if self.raw_channel:
			self.raw_channel.receivedTsidOnid.get().remove(self.gotTsidOnid)
		self.checkingTsidOnid = False

	def closeTunerSetup(self):
		self.restartPrevService(True)

	def isLocked(self):
		return self.frontendStatus.get("tuner_locked", 0) == 1

	def statusMsg(self, msg, blinking=False, timeout=0):			# timeout in seconds
		self.statusMsgBlinking = blinking
		if not blinking:
			self["status_bar"].visible = True
		self["status_bar"].setText(msg)
		self.statusMsgTimeoutTicks = (timeout * 1000 + self.UPDATE_INTERVAL // 2) // self.UPDATE_INTERVAL

	def updateStatus(self):
		self.statusTimer.start(self.UPDATE_INTERVAL, True)
		if self.frontend:
			self.frontend.getFrontendStatus(self.frontendStatus)
		if self.rotor_diseqc:
			self["snr_db"].update()
			self["snr_percentage"].update()
			self["ber_value"].update()
			self["snr_bar"].update()
			self["agc_percentage"].update()
			self["agc_bar"].update()
			self["ber_bar"].update()
			self["lock_state"].update()
			if self["lock_state"].getValue(TunerInfo.LOCK):
				self["lock_on"].show()
			else:
				self["lock_on"].hide()
		if self.statusMsgBlinking:
			self.statusMsgBlinkCount += 1
			if self.statusMsgBlinkCount == self.statusMsgBlinkRate:
				self.statusMsgBlinkCount = 0
				self["status_bar"].visible = not self["status_bar"].visible
		if self.statusMsgTimeoutTicks > 0:
			self.statusMsgTimeoutTicks -= 1
			if self.statusMsgTimeoutTicks == 0:
				self["status_bar"].setText("")
				self.statusMsgBlinking = False
				self["status_bar"].visible = True
		if self.isLocked() and self.isMoving and self.stopOnLock:
			self.stopMoving()
			self.updateColors(self.getCurrentConfigPath())
		if self.collectingStatistics:
			self.low_rate_adapter_count += 1
			if self.low_rate_adapter_count == self.MAX_LOW_RATE_ADAPTER_COUNT:
				self.low_rate_adapter_count = 0
				self.snr_percentage += self["snr_percentage"].getValue(TunerInfo.SNR)
				self.lock_count += self["lock_state"].getValue(TunerInfo.LOCK)
				self.stat_count += 1
				if self.stat_count == self.max_count:
					self.collectingStatistics = False
					count = float(self.stat_count)
					self.lock_count /= count
					self.snr_percentage *= 100.0 / 0x10000 / count
					self.dataAvailable.set()

	def tuningChangedTo(self, tp):

		def setLowRateAdapterCount(symbolrate):
			# change the measurement time and update interval in case of low symbol rate,
			# since more time is needed for the front end in that case.
			# It is an heuristic determination without any pretence. For symbol rates
			# of 5000 the interval is multiplied by 3 until 15000 which is seen
			# as a high symbol rate. Linear interpolation elsewhere.
			return max(int(round((3 - 1) * (symbolrate - 15000) // (5000 - 15000) + 1)), 1)

		self.symbolrate = tp[1]
		self.polarisation = tp[2]
		self.MAX_LOW_RATE_ADAPTER_COUNT = setLowRateAdapterCount(self.symbolrate)
		if len(self.tuner.getTransponderData()):
			transponderdata = ConvertToHumanReadable(self.tuner.getTransponderData(), "DVB-S")
			transponderdataraw = self.tuner.getTransponderData()
		else:
			transponderdata = {}
			transponderdataraw = {}
		polarization_text = ""
		polarization = transponderdata.get("polarization")
		if polarization:
			polarization_text = str(polarization)
			if polarization_text == _("Horizontal"):
				polarization_text = " H"
			elif polarization_text == _("Vertical"):
				polarization_text = " V"
			elif polarization_text == _("Circular right"):
				polarization_text = " R"
			elif polarization_text == _("Circular left"):
				polarization_text = " L"
		frequency_text = ""
		frequency = transponderdataraw.get("frequency")
		if frequency:
			frequency_text = str(frequency // 1000) + polarization_text
		self["frequency_value"].setText(frequency_text)
		symbolrate_text = ""
		symbolrate = transponderdataraw.get("symbol_rate")
		if symbolrate:
			symbolrate_text = str(symbolrate // 1000)
		self["symbolrate_value"].setText(symbolrate_text)
		fec_text = ""
		fec_inner = transponderdata.get("fec_inner")
		if fec_inner:
			if frequency and symbolrate:
				fec_text = str(fec_inner)
		self["fec_value"].setText(fec_text)

	@staticmethod
	def rotorCmd2Step(rotorCmd, stepsize):
		return round(float(rotorCmd & 0xFFF) / 0x10 / stepsize) * (1 - ((rotorCmd & 0x1000) >> 11))

	@staticmethod
	def gotoXcalc(satlon, sitelat, sitelon):
		def azimuth2Rotorcode(angle):
			gotoXtable = (0x00, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0A, 0x0B, 0x0D, 0x0E)
			a = int(round(abs(angle) * 10.0))
			return ((a // 10) << 4) + gotoXtable[a % 10]

		satHourAngle = rotor_calc.calcSatHourangle(satlon, sitelat, sitelon)
		if sitelat >= 0:  # Northern Hemisphere
			rotorCmd = azimuth2Rotorcode(180 - satHourAngle)
			if satHourAngle <= 180:  # the east
				rotorCmd |= 0xE000
			else:					# west
				rotorCmd |= 0xD000
		else:  # Southern Hemisphere
			if satHourAngle <= 180:  # the east
				rotorCmd = azimuth2Rotorcode(satHourAngle) | 0xD000
			else:  # west
				rotorCmd = azimuth2Rotorcode(360 - satHourAngle) | 0xE000
		return rotorCmd

	def gotoX(self, satlon):
		rotorCmd = PositionerSetup.gotoXcalc(satlon, self.sitelat, self.sitelon)
		self.diseqccommand("gotoX", rotorCmd)
		x = PositionerSetup.rotorCmd2Step(rotorCmd, self.tuningstepsize)
		print((_("Rotor step position:") + " %4d") % x, file=log)
		return x

	def getTurningspeed(self):
		if self.polarisation == eDVBFrontendParametersSatellite.Polarisation_Horizontal:
			turningspeed = self.turningspeedH
		else:
			turningspeed = self.turningspeedV
		return max(turningspeed, 0.1)

	TURNING_START_STOP_DELAY = 1.600  # seconds
	MAX_SEARCH_ANGLE = 12.0				# degrees
	MAX_FOCUS_ANGLE = 6.0				# degrees
	LOCK_LIMIT = 0.1					# ratio
	MEASURING_TIME = 2.500				# seconds

	def measure(self, time=MEASURING_TIME):  # time in seconds
		self.snr_percentage = 0.0
		self.lock_count = 0.0
		self.stat_count = 0
		self.low_rate_adapter_count = 0
		self.max_count = max(int((time * 1000 + self.UPDATE_INTERVAL // 2) // self.UPDATE_INTERVAL), 1)
		self.collectingStatistics = True
		self.dataAvailable.clear()
		self.dataAvailable.wait()

	def logMsg(self, msg, timeout=0):
		self.statusMsg(msg, timeout=timeout)
		self.printMsg(msg)

	def sync(self):
		self.lock_count = 0.0
		n = 0
		while self.lock_count < (1 - self.LOCK_LIMIT) and n < 5:
			self.measure(time=0.500)
			n += 1
		if self.lock_count < (1 - self.LOCK_LIMIT):
			return False
		return True

	randomGenerator = None

	def randomBool(self):
		if self.randomGenerator is None:
			self.randomGenerator = SystemRandom()
		return self.randomGenerator.random() >= 0.5

	def gotoXcalibration(self):

		def move(x):
			z = self.gotoX(x + satlon)
			time = int(abs(x - prev_pos) // turningspeed + 2 * self.TURNING_START_STOP_DELAY)
			sleep(time * self.MAX_LOW_RATE_ADAPTER_COUNT)
			return z

		def reportlevels(pos, level, lock):
			print((_("Signal quality") + " %5.1f" + chr(176) + "   : %6.2f") % (pos, level), file=log)
			print((_("Lock ratio") + "     %5.1f" + chr(176) + "   : %6.2f") % (pos, lock), file=log)

		def optimise(readings):
			xi = list(readings.keys())
			yi = [x_y[0] for x_y in readings.values()]
			x0 = sum(map(mul, xi, yi)) // sum(yi)
			xm = xi[yi.index(max(yi))]
			return (x0, xm)

		def toGeopos(x):
			if x < 0:
				return _("W")
			else:
				return _("E")

		def toGeoposEx(x):
			if x < 0:
				return _("west")
			else:
				return _("east")

		self.logMsg(_("GotoX calibration"))
		satlon = self.orbitalposition.float
		print((_("Satellite longitude:") + " %5.1f" + chr(176) + " %s") % (satlon, self.orientation.value), file=log)
		satlon = PositionerSetup.orbital2metric(satlon, self.orientation.value)
		prev_pos = 0.0						# previous relative position w.r.t. satlon
		turningspeed = self.getTurningspeed()

		x = 0.0								# relative position w.r.t. satlon
		dir = 1
		if self.randomBool():
			dir = -dir
		while abs(x) < self.MAX_SEARCH_ANGLE:
			if self.sync():
				break
			x += (1.0 * dir)						# one degree east/west
			self.statusMsg((_("Searching") + " " + toGeoposEx(dir) + " %2d" + chr(176)) % abs(x), blinking=True)
			move(x)
			prev_pos = x
		else:
			x = 0.0
			dir = -dir
			while abs(x) < self.MAX_SEARCH_ANGLE:
				x += (1.0 * dir)					# one degree east/west
				self.statusMsg((_("Searching") + " " + toGeoposEx(dir) + " %2d" + chr(176)) % abs(x), blinking=True)
				move(x)
				prev_pos = x
				if self.sync():
					break
			else:
				msg = _("Cannot find any signal ..., aborting !")
				self.printMsg(msg)
				self.statusMsg("")
				self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
				return
		x = round(x // self.tuningstepsize) * self.tuningstepsize
		move(x)
		prev_pos = x
		measurements = {}
		self.measure()
		print((_("Initial signal quality") + " %5.1f" + chr(176) + ": %6.2f") % (x, self.snr_percentage), file=log)
		print((_("Initial lock ratio") + "     %5.1f" + chr(176) + ": %6.2f") % (x, self.lock_count), file=log)
		measurements[x] = (self.snr_percentage, self.lock_count)

		start_pos = x
		x = 0.0
		dir = 1
		if self.randomBool():
			dir = -dir
		while x < self.MAX_FOCUS_ANGLE:
			x += self.tuningstepsize * dir					# one step east/west
			self.statusMsg((_("Moving") + " " + toGeoposEx(dir) + " %5.1f" + chr(176)) % abs(x + start_pos), blinking=True)
			move(x + start_pos)
			prev_pos = x + start_pos
			self.measure()
			measurements[x + start_pos] = (self.snr_percentage, self.lock_count)
			reportlevels(x + start_pos, self.snr_percentage, self.lock_count)
			if self.lock_count < self.LOCK_LIMIT:
				break
		else:
			msg = _("Cannot determine") + " " + toGeoposEx(dir) + " " + _("limit ..., aborting !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		x = 0.0
		dir = -dir
		self.statusMsg((_("Moving") + " " + toGeoposEx(dir) + " %5.1f" + chr(176)) % abs(start_pos), blinking=True)
		move(start_pos)
		prev_pos = start_pos
		if not self.sync():
			msg = _("Sync failure moving back to origin !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		while abs(x) < self.MAX_FOCUS_ANGLE:
			x += self.tuningstepsize * dir					# one step west/east
			self.statusMsg((_("Moving") + " " + toGeoposEx(dir) + " %5.1f" + chr(176)) % abs(x + start_pos), blinking=True)
			move(x + start_pos)
			prev_pos = x + start_pos
			self.measure()
			measurements[x + start_pos] = (self.snr_percentage, self.lock_count)
			reportlevels(x + start_pos, self.snr_percentage, self.lock_count)
			if self.lock_count < self.LOCK_LIMIT:
				break
		else:
			msg = _("Cannot determine") + " " + toGeoposEx(dir) + " " + _("limit ..., aborting !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		(x0, xm) = optimise(measurements)
		x = move(x0)
		if satlon > 180:
			satlon -= 360
		x0 += satlon
		xm += satlon
		print((_("Weighted position") + "     : %5.1f" + chr(176) + " %s") % (abs(x0), toGeopos(x0)), file=log)
		print((_("Strongest position") + "    : %5.1f" + chr(176) + " %s") % (abs(xm), toGeopos(xm)), file=log)
		self.logMsg((_("Final position at") + " %5.1f" + chr(176) + " %s / %d; " + _("offset is") + " %4.1f" + chr(176)) % (abs(x0), toGeopos(x0), x, x0 - satlon), timeout=10)

	def autofocus(self):

		def move(x):
			if x > 0:
				self.diseqccommand("moveEast", (-x) & 0xFF)
			elif x < 0:
				self.diseqccommand("moveWest", x & 0xFF)
			if x != 0:
				time = int(abs(x) * self.tuningstepsize // turningspeed + 2 * self.TURNING_START_STOP_DELAY)
				sleep(time * self.MAX_LOW_RATE_ADAPTER_COUNT)

		def reportlevels(pos, level, lock):
			print((_("Signal quality") + " [%2d]   : %6.2f") % (pos, level), file=log)
			print((_("Lock ratio") + " [%2d]       : %6.2f") % (pos, lock), file=log)

		def optimise(readings):
			xi = list(readings.keys())
			yi = [x_y1[0] for x_y1 in readings.values()]
			x0 = int(round(sum(map(mul, xi, yi)) // sum(yi)))
			xm = xi[yi.index(max(yi))]
			return (x0, xm)

		def toGeoposEx(x):
			if x < 0:
				return _("west")
			else:
				return _("east")

		self.logMsg(_("Auto focus commencing ..."))
		turningspeed = self.getTurningspeed()
		measurements = {}
		maxsteps = max(min(round(self.MAX_FOCUS_ANGLE // self.tuningstepsize), 0x1F), 3)
		self.measure()
		print((_("Initial signal quality:") + " %6.2f") % self.snr_percentage, file=log)
		print((_("Initial lock ratio") + "    : %6.2f") % self.lock_count, file=log)
		if self.lock_count < 1 - self.LOCK_LIMIT:
			msg = _("There is no signal to lock on !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		print(_("Signal OK, proceeding"), file=log)
		x = 0
		dir = 1
		if self.randomBool():
			dir = -dir
		measurements[x] = (self.snr_percentage, self.lock_count)
		nsteps = 0
		while nsteps < maxsteps:
			x += dir
			self.statusMsg((_("Moving") + " " + toGeoposEx(dir) + " %2d") % abs(x), blinking=True)
			move(dir) 		# one step
			self.measure()
			measurements[x] = (self.snr_percentage, self.lock_count)
			reportlevels(x, self.snr_percentage, self.lock_count)
			if self.lock_count < self.LOCK_LIMIT:
				break
			nsteps += 1
		else:
			msg = _("Cannot determine") + " " + toGeoposEx(dir) + " " + _("limit ..., aborting !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		dir = -dir
		self.statusMsg(_("Moving") + " " + toGeoposEx(dir) + "  0", blinking=True)
		move(-x)
		if not self.sync():
			msg = _("Sync failure moving back to origin !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		x = 0
		nsteps = 0
		while nsteps < maxsteps:
			x += dir
			self.statusMsg((_("Moving") + " " + toGeoposEx(dir) + " %2d") % abs(x), blinking=True)
			move(dir) 		# one step
			self.measure()
			measurements[x] = (self.snr_percentage, self.lock_count)
			reportlevels(x, self.snr_percentage, self.lock_count)
			if self.lock_count < self.LOCK_LIMIT:
				break
			nsteps += 1
		else:
			msg = _("Cannot determine") + " " + toGeoposEx(dir) + " " + _("limit ..., aborting !")
			self.printMsg(msg)
			self.statusMsg("")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=5)
			return
		(x0, xm) = optimise(measurements)
		print((_("Weighted position") + "     : %2d") % x0, file=log)
		print((_("Strongest position") + "    : %2d") % xm, file=log)
		self.logMsg((_("Final position at index") + " %2d (%5.1f" + chr(176) + ")") % (x0, x0 * self.tuningstepsize), timeout=6)
		move(x0 - x)


class Diseqc:
	def __init__(self, frontend):
		self.frontend = frontend

	def command(self, what, param=0):
		if self.frontend:
			cmd = eDVBDiseqcCommand()
			if what == "moveWest":
				string = 'E03169' + ("%02X" % param)
			elif what == "moveEast":
				string = 'E03168' + ("%02X" % param)
			elif what == "moveTo":
				string = 'E0316B' + ("%02X" % param)
			elif what == "store":
				string = 'E0316A' + ("%02X" % param)
			elif what == "gotoX":
				string = 'E0316E' + ("%04X" % param)
			elif what == "calc":
				string = 'E0316F' + ("%06X" % param)
			elif what == "limitOn":
				string = 'E0316A00'
			elif what == "limitOff":
				string = 'E03163'
			elif what == "limitEast":
				string = 'E03166'
			elif what == "limitWest":
				string = 'E03167'
			else:
				string = 'E03160'  # positioner stop

			print("diseqc command:", end=' ')
			print(string)
			cmd.setCommandString(string)
			self.frontend.setTone(iDVBFrontend.toneOff)
			sleep(0.015)  # wait 15msec after disable tone
			self.frontend.sendDiseqc(cmd)
			if string == 'E03160':  # positioner stop
				sleep(0.050)
				self.frontend.sendDiseqc(cmd)  # send 2nd time


class PositionerSetupLog(Screen):
	skin = """
		<screen position="center,center" size="560,400" title="Positioner setup log" >
			<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="buttons/red.png" transparent="1" alphatest="on" />
			<ePixmap name="green"  position="230,0" zPosition="2" size="140,40" pixmap="buttons/green.png" transparent="1" alphatest="on" />
			<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="buttons/blue.png" transparent="1" alphatest="on" />

			<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget name="key_green" position="230,0" size="140,40" halign="center" valign="center"  zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />

			<ePixmap alphatest="on" pixmap="icons/clock.png" position="480,383" size="14,14" zPosition="3"/>
			<widget font="Regular;18" halign="left" position="505,380" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
				<convert type="ClockToText">Default</convert>
			</widget>
			<widget name="list" font="Regular;16" position="10,40" size="540,340" />
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.setTitle(_("Positioner setup log"))
		self["key_red"] = Button(_("Exit"))
		self["key_green"] = Button(_("Save"))
		self["key_blue"] = Button(_("Clear"))
		self["list"] = ScrollLabel(log.getvalue())
		self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ColorActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"save": self.save,
			"blue": self.clear,
			"cancel": self.cancel,
			"ok": self.cancel,
			"left": self["list"].pageUp,
			"right": self["list"].pageDown,
			"up": self["list"].pageUp,
			"down": self["list"].pageDown,
			"pageUp": self["list"].pageUp,
			"pageDown": self["list"].pageDown
		}, -2)

	def save(self):
		try:
			f = open('/tmp/positionersetup.log', 'w')
			f.write(log.getvalue())
			f.close()
			self.session.open(MessageBox, _("Write to /tmp/positionersetup.log"), MessageBox.TYPE_INFO, timeout=5)
		except Exception as e:
			self["list"].setText(_("Failed to write /tmp/positionersetup.log: ") + str(e))
		self.close(True)

	def cancel(self):
		self.close(False)

	def clear(self):
		log.logfile.seek(0)
		log.logfile.truncate()
		self.close(False)


class ONIDTSIDScreen(ConfigListScreen, Screen):
	skin = """
		<screen position="center,center" size="520,250" title="Tune">
			<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphatest="on"/>
			<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphatest="on"/>
			<widget source="key_red" render="Label" position="0,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1"/>
			<widget source="key_green" render="Label" position="140,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1"/>
			<widget name="config" position="10,50" size="500,150" scrollbarMode="showOnDemand" />
			<widget name="introduction" position="60,220" size="450,23" halign="left" font="Regular;20" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skinName = ["ONIDTSIDScreen", "TunerScreen"]
		self.setTitle(_("Enter valid ONID/TSID"))
		ConfigListScreen.__init__(self, None)
		self.transponderTsid = NoSave(ConfigInteger(default=0, limits=(0, 65535)))
		self.transponderOnid = NoSave(ConfigInteger(default=0, limits=(0, 65535)))
		self.createSetup()
		self["actions"] = NumberActionMap(["SetupActions", "ColorActions"],
		{
			"ok": self.keyGo,
			"cancel": self.keyCancel,
			"red": self.keyCancel,
			"green": self.keyGo,
		}, -2)

		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("OK"))
		self["introduction"] = Label(_("Valid ONID/TSID look at www.lyngsat.com..."))

	def createSetup(self):
		self.list = []
		self.list.append(getConfigListEntry(_("ONID"), self.transponderOnid))
		self.list.append(getConfigListEntry(_("TSID"), self.transponderTsid))
		self["config"].list = self.list

	def keyGo(self):
		onid = int(self.transponderOnid.value)
		tsid = int(self.transponderTsid.value)
		if onid == 0 and tsid == 0:
			self.close(None)
		else:
			returnvalue = (onid, tsid)
			self.close(returnvalue)

	def keyCancel(self):
		self.close(None)


class TunerScreen(ConfigListScreen, Screen):
	skin = """
		<screen position="center,center" size="520,450" title="Tune">
			<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphatest="on"/>
			<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphatest="on"/>
			<widget source="key_red" render="Label" position="0,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1"/>
			<widget source="key_green" render="Label" position="140,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1"/>
			<widget name="config" position="10,50" size="500,350" scrollbarMode="showOnDemand" />
			<widget name="introduction" position="60,420" size="450,23" halign="left" font="Regular;20" />
		</screen>"""

	def __init__(self, session, feid, fe_data):
		self.feid = feid
		self.fe_data = fe_data
		Screen.__init__(self, session)
		self.setTitle(_("Tune"))
		ConfigListScreen.__init__(self, None)
		self.createConfig(fe_data)
		self.initialSetup()
		self.createSetup()
		self.tuning.sat.addNotifier(self.tuningSatChanged)
		self.tuning.type.addNotifier(self.tuningTypeChanged)
		self.scan_sat.system.addNotifier(self.systemChanged)

		self["actions"] = NumberActionMap(["SetupActions", "ColorActions"],
		{
			"ok": self.keyGo,
			"cancel": self.keyCancel,
			"red": self.keyCancel,
			"green": self.keyGo,
		}, -2)

		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("OK"))
		self["introduction"] = Label(_("Press OK, save and exit..."))

	def createConfig(self, frontendData):
		satlist = nimmanager.getRotorSatListForNim(self.feid)
		orb_pos = self.fe_data.get("orbital_position", None)
		self.tuning = ConfigSubsection()
		self.tuning.type = ConfigSelection(
				default="manual_transponder",
				choices={"manual_transponder": _("Manual transponder"),
							"predefined_transponder": _("Predefined transponder")})
		self.tuning.sat = ConfigSatlist(list=satlist)
		if orb_pos is not None:
			orb_pos_str = str(orb_pos)
			for sat in satlist:
				if sat[0] == orb_pos and self.tuning.sat.value != orb_pos_str:
					self.tuning.sat.value = orb_pos_str
		self.updateTransponders()

		defaultSat = {
			"orbpos": 192,
			"system": eDVBFrontendParametersSatellite.System_DVB_S,
			"frequency": 11836,
			"inversion": eDVBFrontendParametersSatellite.Inversion_Unknown,
			"symbolrate": 27500,
			"polarization": eDVBFrontendParametersSatellite.Polarisation_Horizontal,
			"fec": eDVBFrontendParametersSatellite.FEC_Auto,
			"fec_s2": eDVBFrontendParametersSatellite.FEC_9_10,
			"modulation": eDVBFrontendParametersSatellite.Modulation_QPSK,
			"pls_mode": eDVBFrontendParametersSatellite.PLS_Gold,
			"pls_code": eDVBFrontendParametersSatellite.PLS_Default_Gold_Code}
		if frontendData is not None:
			ttype = frontendData.get("tuner_type", "UNKNOWN")
			defaultSat["system"] = frontendData.get("system", eDVBFrontendParametersSatellite.System_DVB_S)
			defaultSat["frequency"] = frontendData.get("frequency", 0) // 1000
			defaultSat["inversion"] = frontendData.get("inversion", eDVBFrontendParametersSatellite.Inversion_Unknown)
			defaultSat["symbolrate"] = frontendData.get("symbol_rate", 0) // 1000
			defaultSat["polarization"] = frontendData.get("polarization", eDVBFrontendParametersSatellite.Polarisation_Horizontal)
			if defaultSat["system"] == eDVBFrontendParametersSatellite.System_DVB_S2:
				defaultSat["fec_s2"] = frontendData.get("fec_inner", eDVBFrontendParametersSatellite.FEC_Auto)
				defaultSat["rolloff"] = frontendData.get("rolloff", eDVBFrontendParametersSatellite.RollOff_alpha_0_35)
				defaultSat["pilot"] = frontendData.get("pilot", eDVBFrontendParametersSatellite.Pilot_Unknown)
				defaultSat["is_id"] = frontendData.get("is_id", eDVBFrontendParametersSatellite.No_Stream_Id_Filter)
				defaultSat["pls_mode"] = frontendData.get("pls_mode", eDVBFrontendParametersSatellite.PLS_Gold)
				defaultSat["pls_code"] = frontendData.get("pls_code", eDVBFrontendParametersSatellite.PLS_Default_Gold_Code)
				defaultSat["t2mi_plp_id"] = frontendData.get("t2mi_plp_id", eDVBFrontendParametersSatellite.No_T2MI_PLP_Id)
				defaultSat["t2mi_pid"] = frontendData.get("t2mi_pid", eDVBFrontendParametersSatellite.T2MI_Default_Pid)
			else:
				defaultSat["fec"] = frontendData.get("fec_inner", eDVBFrontendParametersSatellite.FEC_Auto)
			defaultSat["modulation"] = frontendData.get("modulation", eDVBFrontendParametersSatellite.Modulation_QPSK)
			defaultSat["orbpos"] = frontendData.get("orbital_position", 0)

		self.scan_sat = ConfigSubsection()
		self.scan_sat.system = ConfigSelection(default=defaultSat["system"], choices=[
			(eDVBFrontendParametersSatellite.System_DVB_S, _("DVB-S")),
			(eDVBFrontendParametersSatellite.System_DVB_S2, _("DVB-S2"))])
		self.scan_sat.frequency = ConfigInteger(default=defaultSat["frequency"], limits=(1, 99999))
		self.scan_sat.inversion = ConfigSelection(default=defaultSat["inversion"], choices=[
			(eDVBFrontendParametersSatellite.Inversion_Off, _("Off")),
			(eDVBFrontendParametersSatellite.Inversion_On, _("On")),
			(eDVBFrontendParametersSatellite.Inversion_Unknown, _("Auto"))])
		self.scan_sat.symbolrate = ConfigInteger(default=defaultSat["symbolrate"], limits=(1, 99999))
		self.scan_sat.polarization = ConfigSelection(default=defaultSat["polarization"], choices=[
			(eDVBFrontendParametersSatellite.Polarisation_Horizontal, _("horizontal")),
			(eDVBFrontendParametersSatellite.Polarisation_Vertical, _("vertical")),
			(eDVBFrontendParametersSatellite.Polarisation_CircularLeft, _("circular left")),
			(eDVBFrontendParametersSatellite.Polarisation_CircularRight, _("circular right"))])
		self.scan_sat.fec = ConfigSelection(default=defaultSat["fec"], choices=[
			(eDVBFrontendParametersSatellite.FEC_Auto, _("Auto")),
			(eDVBFrontendParametersSatellite.FEC_1_2, "1/2"),
			(eDVBFrontendParametersSatellite.FEC_2_3, "2/3"),
			(eDVBFrontendParametersSatellite.FEC_3_4, "3/4"),
			(eDVBFrontendParametersSatellite.FEC_5_6, "5/6"),
			(eDVBFrontendParametersSatellite.FEC_7_8, "7/8"),
			(eDVBFrontendParametersSatellite.FEC_None, _("None"))])
		self.scan_sat.fec_s2 = ConfigSelection(default=defaultSat["fec_s2"], choices=[
			(eDVBFrontendParametersSatellite.FEC_1_2, "1/2"),
			(eDVBFrontendParametersSatellite.FEC_2_3, "2/3"),
			(eDVBFrontendParametersSatellite.FEC_3_4, "3/4"),
			(eDVBFrontendParametersSatellite.FEC_3_5, "3/5"),
			(eDVBFrontendParametersSatellite.FEC_4_5, "4/5"),
			(eDVBFrontendParametersSatellite.FEC_5_6, "5/6"),
			(eDVBFrontendParametersSatellite.FEC_7_8, "7/8"),
			(eDVBFrontendParametersSatellite.FEC_8_9, "8/9"),
			(eDVBFrontendParametersSatellite.FEC_9_10, "9/10")])
		self.scan_sat.modulation = ConfigSelection(default=defaultSat["modulation"], choices=[
			(eDVBFrontendParametersSatellite.Modulation_QPSK, "QPSK"),
			(eDVBFrontendParametersSatellite.Modulation_8PSK, "8PSK"),
			(eDVBFrontendParametersSatellite.Modulation_16APSK, "16APSK"),
			(eDVBFrontendParametersSatellite.Modulation_32APSK, "32APSK")])
		self.scan_sat.rolloff = ConfigSelection(default=defaultSat.get("rolloff", eDVBFrontendParametersSatellite.RollOff_alpha_0_35), choices=[
			(eDVBFrontendParametersSatellite.RollOff_alpha_0_35, "0.35"),
			(eDVBFrontendParametersSatellite.RollOff_alpha_0_25, "0.25"),
			(eDVBFrontendParametersSatellite.RollOff_alpha_0_20, "0.20"),
			(eDVBFrontendParametersSatellite.RollOff_auto, _("Auto"))])
		self.scan_sat.pilot = ConfigSelection(default=defaultSat.get("pilot", eDVBFrontendParametersSatellite.Pilot_Unknown), choices=[
			(eDVBFrontendParametersSatellite.Pilot_Off, _("Off")),
			(eDVBFrontendParametersSatellite.Pilot_On, _("On")),
			(eDVBFrontendParametersSatellite.Pilot_Unknown, _("Auto"))])
		self.scan_sat.is_id = ConfigInteger(default=defaultSat.get("is_id", 0), limits=(0, 255))
		self.scan_sat.pls_mode = ConfigSelection(default=defaultSat.get("pls_mode", eDVBFrontendParametersSatellite.PLS_Gold), choices=[
			(eDVBFrontendParametersSatellite.PLS_Root, _("Root")),
			(eDVBFrontendParametersSatellite.PLS_Gold, _("Gold")),
			(eDVBFrontendParametersSatellite.PLS_Combo, _("Combo"))])
		self.scan_sat.pls_code = ConfigInteger(default=defaultSat.get("pls_code", eDVBFrontendParametersSatellite.PLS_Default_Gold_Code), limits=(0, 262142))
		self.scan_sat.t2mi_plp_id = ConfigInteger(default=defaultSat.get("t2mi_plp_id", eDVBFrontendParametersSatellite.No_T2MI_PLP_Id), limits=(0, 255))
		self.scan_sat.t2mi_pid = ConfigInteger(default=defaultSat.get("t2mi_pid", eDVBFrontendParametersSatellite.T2MI_Default_Pid), limits=(0, 8191))

	def initialSetup(self):
		currtp = self.transponderToString([None, self.scan_sat.frequency.value, self.scan_sat.symbolrate.value, self.scan_sat.polarization.value])
		if currtp in self.tuning.transponder.choices:
			self.tuning.type.value = "predefined_transponder"
		else:
			self.tuning.type.value = "manual_transponder"

	def createSetup(self):
		self.list = []
		self.list.append(getConfigListEntry(_('Tune'), self.tuning.type))
		self.list.append(getConfigListEntry(_('Satellite'), self.tuning.sat))
		nim = nimmanager.nim_slots[self.feid]

		if self.tuning.type.value == "manual_transponder":
			if nim.isCompatible("DVB-S2"):
				self.list.append(getConfigListEntry(_('System'), self.scan_sat.system))
			else:
				# downgrade to dvb-s, in case a -s2 config was active
				self.scan_sat.system.value = eDVBFrontendParametersSatellite.System_DVB_S
			self.list.append(getConfigListEntry(_('Frequency'), self.scan_sat.frequency))
			self.list.append(getConfigListEntry(_("Polarisation"), self.scan_sat.polarization))
			self.list.append(getConfigListEntry(_('Symbol rate'), self.scan_sat.symbolrate))
			if self.scan_sat.system.value == eDVBFrontendParametersSatellite.System_DVB_S:
				self.list.append(getConfigListEntry(_("FEC"), self.scan_sat.fec))
				self.list.append(getConfigListEntry(_('Inversion'), self.scan_sat.inversion))
			elif self.scan_sat.system.value == eDVBFrontendParametersSatellite.System_DVB_S2:
				self.list.append(getConfigListEntry(_("FEC"), self.scan_sat.fec_s2))
				self.list.append(getConfigListEntry(_('Inversion'), self.scan_sat.inversion))
				self.modulationEntry = getConfigListEntry(_('Modulation'), self.scan_sat.modulation)
				self.list.append(self.modulationEntry)
				self.list.append(getConfigListEntry(_('Roll-off'), self.scan_sat.rolloff))
				self.list.append(getConfigListEntry(_('Pilot'), self.scan_sat.pilot))
				if nim.isMultistream():
					self.list.append(getConfigListEntry(_('Input Stream ID'), self.scan_sat.is_id))
					self.list.append(getConfigListEntry(_('PLS Mode'), self.scan_sat.pls_mode))
					self.list.append(getConfigListEntry(_('PLS Code'), self.scan_sat.pls_code))
				if nim.isT2MI():
					self.list.append(getConfigListEntry(_('T2MI PLP ID'), self.scan_sat.t2mi_plp_id))
					self.list.append(getConfigListEntry(_('T2MI PID'), self.scan_sat.t2mi_pid))
		else:  # "predefined_transponder"
			self.list.append(getConfigListEntry(_("Transponder"), self.tuning.transponder))
			currtp = self.transponderToString([None, self.scan_sat.frequency.value, self.scan_sat.symbolrate.value, self.scan_sat.polarization.value])
			self.tuning.transponder.setValue(currtp)
		self["config"].list = self.list

	def tuningSatChanged(self, *parm):
		self.updateTransponders()
		self.createSetup()

	def tuningTypeChanged(self, *parm):
		self.createSetup()

	def systemChanged(self, *parm):
		self.createSetup()

	def transponderToString(self, tr, scale=1):
		if tr[3] == 0:
			pol = "H"
		elif tr[3] == 1:
			pol = "V"
		elif tr[3] == 2:
			pol = "CL"
		elif tr[3] == 3:
			pol = "CR"
		else:
			pol = "??"
		return str(tr[1] // scale) + "," + pol + "," + str(tr[2] // scale)

	def updateTransponders(self):
		if len(self.tuning.sat.choices):
			transponderlist = nimmanager.getTransponders(int(self.tuning.sat.value), self.feid)
			tps = []
			for transponder in transponderlist:
				tps.append(self.transponderToString(transponder, scale=1000))
			self.tuning.transponder = ConfigSelection(choices=tps)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)

	def keyRight(self):
		ConfigListScreen.keyRight(self)

	def keyGo(self):
		returnvalue = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -1, 0, 1, -1)
		satpos = int(self.tuning.sat.value)
		if self.tuning.type.value == "manual_transponder":
			if self.scan_sat.system.value == eDVBFrontendParametersSatellite.System_DVB_S2:
				fec = self.scan_sat.fec_s2.value
			else:
				fec = self.scan_sat.fec.value
			returnvalue = (
				self.scan_sat.frequency.value,
				self.scan_sat.symbolrate.value,
				self.scan_sat.polarization.value,
				fec,
				self.scan_sat.inversion.value,
				satpos,
				self.scan_sat.system.value,
				self.scan_sat.modulation.value,
				self.scan_sat.rolloff.value,
				self.scan_sat.pilot.value,
				self.scan_sat.is_id.value,
				self.scan_sat.pls_mode.value,
				self.scan_sat.pls_code.value,
				self.scan_sat.t2mi_plp_id.value,
				self.scan_sat.t2mi_pid.value)
		elif self.tuning.type.value == "predefined_transponder":
			transponder = nimmanager.getTransponders(satpos)[self.tuning.transponder.index]
			returnvalue = (transponder[1] // 1000, transponder[2] // 1000,
				transponder[3], transponder[4], 2, satpos, transponder[5], transponder[6], transponder[8], transponder[9], transponder[10], transponder[11], transponder[12], transponder[13], transponder[14])
		self.close(returnvalue)

	def keyCancel(self):
		self.close(None)


class RotorNimSelection(Screen):
	skin = """
		<screen position="center,center" size="400,130" title="Select slot">
			<widget name="nimlist" position="20,10" size="360,100" />
		</screen>"""

	def __init__(self, session, nimList):
		Screen.__init__(self, session)
		self.setTitle(_("Select slot"))
		nimMenuList = []
		for nim in nimList:
			nimMenuList.append((nimmanager.nim_slots[nim].friendly_full_description, nim))

		self["nimlist"] = MenuList(nimMenuList)

		self["actions"] = ActionMap(["OkCancelActions"],
		{
			"ok": self.okbuttonClick,
			"cancel": self.close
		}, -1)

	def okbuttonClick(self):
		self.session.openWithCallback(self.close, PositionerSetup, self["nimlist"].getCurrent()[1])


def getUsableRotorNims(only_first=False):
	usableRotorNims = []
	nimList = nimmanager.getNimListOfType("DVB-S")
	for nim in nimList:
		if not nimmanager.nim_slots[nim].isFBCLink() and nimmanager.getRotorSatListForNim(nim, only_first=only_first):
			usableRotorNims.append(nim)
			if only_first:
				break
	return usableRotorNims


def PositionerMain(session, **kwargs):
	usableRotorNims = getUsableRotorNims()
	if len(usableRotorNims) == 1:
		session.open(PositionerSetup, usableRotorNims[0])
	elif len(usableRotorNims) > 1:
		session.open(RotorNimSelection, usableRotorNims)


def PositionerSetupStart(menuid, **kwargs):
	if menuid == "scan" and getUsableRotorNims(True):
		return [(_("Positioner setup"), PositionerMain, "positioner_setup", None)]
	return []


def Plugins(**kwargs):
	if nimmanager.hasNimType("DVB-S"):
		return PluginDescriptor(name=_("Positioner setup"), description=_("Setup your positioner"), where=PluginDescriptor.WHERE_MENU, needsRestart=False, fnc=PositionerSetupStart)
	else:
		return []
