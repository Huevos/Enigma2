from enigma import eDVBFrontendParametersSatellite, eDVBFrontendParametersTerrestrial, eDVBFrontendParametersCable, eDVBFrontendParametersATSC, eDVBFrontendParameters, eDVBResourceManager, eTimer


class Tuner:
	def __init__(self, frontend, ignore_rotor=False):
		self.frontend = frontend
		self.ignore_rotor = ignore_rotor

	# transponder = (0:frequency 1:symbolrate 2:polarisation 3:fec 4:inversion 5:orbpos 6:system 7:modulation 8:rolloff 9:pilot 10:is_id 11:pls_mode 12:pls_code 13:t2mi_plp_id 14:t2mi_pid 15:tsid 16:onid)
	def tune(self, transponder):
		if self.frontend:
			print("[TuneTest] tuning to transponder with data", transponder)
			parm = eDVBFrontendParametersSatellite()
			parm.frequency = transponder[0] * 1000
			parm.symbol_rate = transponder[1] * 1000
			parm.polarisation = transponder[2]
			parm.fec = transponder[3]
			parm.inversion = transponder[4]
			parm.orbital_position = transponder[5]
			parm.system = transponder[6]
			parm.modulation = transponder[7]
			parm.rolloff = transponder[8]
			parm.pilot = transponder[9]
			if len(transponder) > 12:
				parm.is_id = transponder[10]
				parm.pls_mode = transponder[11]
				parm.pls_code = transponder[12]
			else:
				parm.is_id = eDVBFrontendParametersSatellite.No_Stream_Id_Filter
				parm.pls_mode = eDVBFrontendParametersSatellite.PLS_Gold
				parm.pls_code = eDVBFrontendParametersSatellite.PLS_Default_Gold_Code
			if len(transponder) > 14:
				parm.t2mi_plp_id = transponder[13]
				parm.t2mi_pid = transponder[14]
			else:
				parm.t2mi_plp_id = eDVBFrontendParametersSatellite.No_T2MI_PLP_Id
				parm.t2mi_pid = eDVBFrontendParametersSatellite.T2MI_Default_Pid
			self.tuneSatObj(parm)

	def tuneSatObj(self, transponderObj):
		if self.frontend:
			feparm = eDVBFrontendParameters()
			feparm.setDVBS(transponderObj, self.ignore_rotor)
			self.lastparm = feparm
			self.frontend.tune(feparm)

	def tuneTerr(self, frequency,
		inversion=2, bandwidth=7000000, fechigh=6, feclow=6,
		modulation=2, transmission=2, guard=4,
		hierarchy=4, system=0, plp_id=0):
		if self.frontend:
			print("[TuneTest] tuning to transponder with data", [frequency, inversion, bandwidth, fechigh, feclow, modulation, transmission, guard, hierarchy, system, plp_id])
			parm = eDVBFrontendParametersTerrestrial()
			parm.frequency = frequency
			parm.inversion = inversion
			parm.bandwidth = bandwidth
			parm.code_rate_HP = fechigh
			parm.code_rate_LP = feclow
			parm.modulation = modulation
			parm.transmission_mode = transmission
			parm.guard_interval = guard
			parm.hierarchy = hierarchy
			parm.system = system
			parm.plp_id = plp_id
			self.tuneTerrObj(parm)

	def tuneTerrObj(self, transponderObj):
		if self.frontend:
			feparm = eDVBFrontendParameters()
			feparm.setDVBT(transponderObj)
			self.lastparm = feparm
			self.frontend.tune(feparm)

	def tuneCab(self, transponder):
		if self.frontend:
			print("[TuneTest] tuning to transponder with data", transponder)
			parm = eDVBFrontendParametersCable()
			parm.frequency = transponder[0]
			parm.symbol_rate = transponder[1]
			parm.modulation = transponder[2]
			parm.fec_inner = transponder[3]
			parm.inversion = transponder[4]
			#parm.system = transponder[5]
			self.tuneCabObj(parm)

	def tuneCabObj(self, transponderObj):
		if self.frontend:
			feparm = eDVBFrontendParameters()
			feparm.setDVBC(transponderObj)
			self.lastparm = feparm
			self.frontend.tune(feparm)

	def tuneATSC(self, transponder):
		if self.frontend:
			print("[TuneTest] tuning to transponder with data", transponder)
			parm = eDVBFrontendParametersATSC()
			parm.frequency = transponder[0]
			parm.modulation = transponder[1]
			parm.inversion = transponder[2]
			parm.system = transponder[3]
			self.tuneATSCObj(parm)

	def tuneATSCObj(self, transponderObj):
		if self.frontend:
			feparm = eDVBFrontendParameters()
			feparm.setATSC(transponderObj)
			self.lastparm = feparm
			self.frontend.tune(feparm)

	def retune(self):
		if self.frontend:
			self.frontend.tune(self.lastparm)

	def getTransponderData(self):
		ret = {}
		if self.frontend:
			self.frontend.getTransponderData(ret, True)
		return ret

# tunes a list of transponders and checks, if they lock and optionally checks the onid/tsid combination
# 1) add transponders with addTransponder()
# 2) call run(<checkPIDs = True>)
# 3) finishedChecking() is called, when the run is finished


class TuneTest:
	def __init__(self, feid, stopOnSuccess=-1, stopOnError=-1):
		self.stopOnSuccess = stopOnSuccess
		self.stopOnError = stopOnError
		self.feid = feid
		self.transponderlist = []
		self.currTuned = None
		print("[TuneTest] for feid %d" % self.feid)
		if not self.openFrontend():
			self.oldref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			self.session.nav.stopService()  # try to disable foreground service
			if not self.openFrontend():
				if self.session.pipshown:  # try to disable pip
					if hasattr(self.session, 'infobar'):
						if self.session.infobar.servicelist.dopipzap:
							self.session.infobar.servicelist.togglePipzap()
					if hasattr(self.session, 'pip'):
						del self.session.pip
					self.session.pipshown = False
					if not self.openFrontend():
						self.frontend = None  # in normal case this should not happen
		self.tuner = Tuner(self.frontend)
		self.timer = eTimer()
		self.timer.callback.append(self.updateStatus)

	def gotTsidOnid(self, tsid, onid):
		print("[TuneTest] ******** got tsid, onid:", tsid, onid)
		if tsid != -1 and onid != -1:
			self.pidStatus = self.INTERNAL_PID_STATUS_SUCCESSFUL
			self.tsid = tsid
			self.onid = onid
		else:
			self.pidStatus = self.INTERNAL_PID_STATUS_FAILED
			self.tsid = -1
			self.onid = -1
		self.timer.start(100, True)

	def updateStatus(self):
		tunerdict = {}
		self.frontend.getFrontendStatus(tunerdict)
		stop = False

		print("[TuneTest] status:", tunerdict)
		if tunerdict["tuner_state"] == "TUNING":
			print("[TuneTest] TUNING")
			self.timer.start(100, True)
			self.progressCallback((self.getProgressLength(), self.tuningtransponder, self.STATUS_TUNING, self.currTuned))
		elif self.checkPIDs and self.pidStatus == self.INTERNAL_PID_STATUS_NOOP:
			print("[TuneTest] 2nd choice")
			if tunerdict["tuner_state"] == "LOCKED":
				print("[TuneTest] acquiring TSID/ONID")
				self.raw_channel.receivedTsidOnid.get().append(self.gotTsidOnid)
				self.raw_channel.requestTsidOnid()
				self.pidStatus = self.INTERNAL_PID_STATUS_WAITING
			else:
				self.pidStatus = self.INTERNAL_PID_STATUS_FAILED
		elif self.checkPIDs and self.pidStatus == self.INTERNAL_PID_STATUS_WAITING:
			print("[TuneTest] waiting for pids")
		else:
			if tunerdict["tuner_state"] == "LOSTLOCK" or tunerdict["tuner_state"] == "FAILED":
				self.tuningtransponder = self.nextTransponder()
				self.failedTune.append([self.currTuned, self.oldTuned, "tune_failed", tunerdict])  # last parameter is the frontend status)
				if self.stopOnError != -1 and self.stopOnError <= len(self.failedTune):
					stop = True
			elif tunerdict["tuner_state"] == "LOCKED":
				if self.checkPIDs:
					if self.currTuned is not None:
						if self.tsid != self.currTuned[15] or self.onid != self.currTuned[16]:
							self.failedTune.append([self.currTuned, self.oldTuned, "pids_failed", {"real": (self.tsid, self.onid), "expected": (self.currTuned[15], self.currTuned[16])}, tunerdict])  # last parameter is the frontend status
						else:
							self.successfullyTune.append([self.currTuned, self.oldTuned, tunerdict])  # 3rd parameter is the frontend status
							if self.stopOnSuccess != -1 and self.stopOnSuccess <= len(self.successfullyTune):
								stop = True
				else:
					self.successfullyTune.append([self.currTuned, self.oldTuned, tunerdict])  # 3rd parameter is the frontend status
					if self.stopOnSuccess != -1 and self.stopOnSuccess <= len(self.successfullyTune):
						stop = True
				self.tuningtransponder = self.nextTransponder()
			else:
				print("[TuneTest] ************* tuner_state:", tunerdict["tuner_state"])

			self.progressCallback((self.getProgressLength(), self.tuningtransponder, self.STATUS_NOOP, self.currTuned))

			if not stop:
				self.tune()
		if self.tuningtransponder < len(self.transponderlist) and not stop:
			if self.pidStatus != self.INTERNAL_PID_STATUS_WAITING:
				self.timer.start(100, True)
				print("[TuneTest] restart timer")
			else:
				print("[TuneTest] not restarting timers (waiting for pids)")
		else:
			self.progressCallback((self.getProgressLength(), len(self.transponderlist), self.STATUS_DONE, self.currTuned))
			print("[TuneTest] finishedChecking")
			self.finishedChecking()

	def firstTransponder(self):
		print("[TuneTest] firstTransponder:")
		index = 0
		if self.checkPIDs:
			print("[TuneTest] checkPIDs-loop")
			# check for tsid != -1 and onid != -1
			print("[TuneTest] index:", index)
			print("[TuneTest] len(self.transponderlist):", len(self.transponderlist))
			while (index < len(self.transponderlist) and (self.transponderlist[index][15] == -1 or self.transponderlist[index][16] == -1)):
				index += 1
		print("[TuneTest] FirstTransponder final index:", index)
		return index

	def nextTransponder(self):
		print("[TuneTest] getting next transponder", self.tuningtransponder)
		index = self.tuningtransponder + 1
		if self.checkPIDs:
			print("[TuneTest] checkPIDs-loop")
			# check for tsid != -1 and onid != -1
			print("[TuneTest] index:", index)
			print("[TuneTest] len(self.transponderlist):", len(self.transponderlist))
			while (index < len(self.transponderlist) and (self.transponderlist[index][15] == -1 or self.transponderlist[index][16] == -1)):
				index += 1
		print("[TuneTest] next transponder index:", index)
		return index

	def finishedChecking(self):
		print("[TuneTest] finished testing")
		print("[TuneTest] successfull:", self.successfullyTune)
		print("[TuneTest] failed:", self.failedTune)

	def openFrontend(self):
		res_mgr = eDVBResourceManager.getInstance()
		if res_mgr:
			self.raw_channel = res_mgr.allocateRawChannel(self.feid)
			if self.raw_channel:
				self.frontend = self.raw_channel.getFrontend()
				if self.frontend:
					return True
				else:
					print("[TuneTest] getFrontend failed")
			else:
				print("[TuneTest] getRawChannel failed")
		else:
			print("[TuneTest] getResourceManager instance failed")
		return False

	def tune(self):
		print("[TuneTest] tuning to", self.tuningtransponder)
		if self.tuningtransponder < len(self.transponderlist):
			self.pidStatus = self.INTERNAL_PID_STATUS_NOOP
			self.oldTuned = self.currTuned
			self.currTuned = self.transponderlist[self.tuningtransponder]
			self.tuner.tune(self.transponderlist[self.tuningtransponder])

	INTERNAL_PID_STATUS_NOOP = 0
	INTERNAL_PID_STATUS_WAITING = 1
	INTERNAL_PID_STATUS_SUCCESSFUL = 2
	INTERNAL_PID_STATUS_FAILED = 3

	def run(self, checkPIDs=False):
		self.checkPIDs = checkPIDs
		self.pidStatus = self.INTERNAL_PID_STATUS_NOOP
		self.failedTune = []
		self.successfullyTune = []
		self.tuningtransponder = self.firstTransponder()
		self.tune()
		self.progressCallback((self.getProgressLength(), self.tuningtransponder, self.STATUS_START, self.currTuned))
		self.timer.start(100, True)

	# transponder = (0:frequency 1:symbolrate 2:polarisation 3:fec 4:inversion 5:orbpos 6:system 7:modulation 8:rolloff 9:pilot 10:is_id 11:pls_mode 12:pls_code 13:t2mi_plp_id 14:t2mi_pid 15:tsid 16:onid)
	def addTransponder(self, transponder):
		self.transponderlist.append(transponder)

	def clearTransponder(self):
		self.transponderlist = []

	def getProgressLength(self):
		count = 0
		if self.stopOnError == -1:
			count = len(self.transponderlist)
		else:
			if count < self.stopOnError:
				count = self.stopOnError
		if self.stopOnSuccess == -1:
			count = len(self.transponderlist)
		else:
			if count < self.stopOnSuccess:
				count = self.stopOnSuccess
		return count

	STATUS_START = 0
	STATUS_TUNING = 1
	STATUS_DONE = 2
	STATUS_NOOP = 3
	# can be overwritten
	# progress = (range, value, status, transponder)

	def progressCallback(self, progress):
		pass
