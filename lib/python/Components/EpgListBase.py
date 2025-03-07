
from enigma import eEPGCache, eListbox, eListboxPythonMultiContent, eServiceReference, eSize

from Components.GUIComponent import GUIComponent
from Tools.Alternatives import CompareWithAlternatives
from Tools.Directories import SCOPE_CURRENT_SKIN, resolveFilename
from Tools.LoadPixmap import LoadPixmap
from skin import parseScale


class EPGListBase(GUIComponent):
	def __init__(self, session, selChangedCB=None):
		GUIComponent.__init__(self)

		self.session = session
		self.onSelChanged = []
		if selChangedCB is not None:
			self.onSelChanged.append(selChangedCB)
		self.l = eListboxPythonMultiContent()
		self.epgcache = eEPGCache.getInstance()

		# Load the common clock icons.
		self.clocks = [
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_pre.png")),
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_post.png")),
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_prepost.png")),
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock.png")),
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_zap.png")),
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_zaprec.png"))
		]
		self.selclocks = [
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_selpre.png")) or self.clocks[0],
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_selpost.png")) or self.clocks[1],
			LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_selprepost.png")) or self.clocks[2],
			self.clocks[3],
			self.clocks[4],
			self.clocks[5]
		]

		self.autotimericon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/epgclock_autotimer.png"))
		try:
			from Plugins.SystemPlugins.IceTV import loadIceTVIcon
			self.icetvicon = loadIceTVIcon("epgclock_icetv.png")
		except ImportError:
			self.icetvicon = None

		self.listHeight = 0
		self.listWidth = 0
		self.skinItemHeight = 0
		self.numberOfRows = 0

	def applySkin(self, desktop, screen):
		if self.skinAttributes is not None:
			attribs = []
			for (attrib, value) in self.skinAttributes:
				if attrib == "itemHeight":
					self.skinItemHeight = parseScale(value)
				elif attrib == "NumberOfRows":  # for compatibility with ATV skins
					self.numberOfRows = int(value)
				else:
					attribs.append((attrib, value))
			self.skinAttributes = attribs
		rc = GUIComponent.applySkin(self, desktop, screen)
		self.skinListHeight = self.listHeight = self.instance.size().height()
		self.listWidth = self.instance.size().width()
		self.setFontsize()
		self.setItemsPerPage()
		return rc

	def setItemsPerPage(self, defaultItemHeight=54):
		numberOfRows = self.epgConfig.itemsperpage.value or self.numberOfRows
		itemHeight = (self.skinListHeight // numberOfRows if numberOfRows > 0 else self.skinItemHeight) or defaultItemHeight
		self.l.setItemHeight(itemHeight)
		self.instance.resize(eSize(self.listWidth, self.skinListHeight // itemHeight * itemHeight))
		self.listHeight = self.instance.size().height()
		self.listWidth = self.instance.size().width()
		self.itemHeight = itemHeight

	def getEventFromId(self, service, eventId):
		event = None
		if self.epgcache is not None and eventId is not None:
			event = self.epgcache.lookupEventId(service.ref, eventId)
		return event

	def getSelectionPosition(self):
		# Adjust absolute index to index in displayed view
		rowCount = self.listHeight // self.itemHeight
		index = self.l.getCurrentSelectionIndex() % rowCount
		sely = self.instance.position().y() + self.itemHeight * index
		if sely >= self.instance.position().y() + self.listHeight:
			sely -= self.listHeight
		return self.listWidth, sely

	def getIndexFromService(self, serviceref):
		if serviceref is not None:
			for x in range(len(self.list)):
				if CompareWithAlternatives(self.list[x][0], serviceref):
					return x
				if CompareWithAlternatives(self.list[x][1], serviceref):
					return x
		return None

	def getCurrentIndex(self):
		return self.instance.getCurrentIndex()

	def moveToService(self, serviceref):
		if not serviceref:
			return
		newIdx = self.getIndexFromService(serviceref)
		if newIdx is None:
			newIdx = 0
		self.setCurrentIndex(newIdx)

	def setCurrentIndex(self, index):
		if self.instance is not None:
			self.instance.moveSelectionTo(index)

	def moveTo(self, dir):
		if self.instance is not None:
			self.instance.moveSelection(dir)

	def getCurrent(self):
		tmp = self.l.getCurrentSelection()
		if tmp is None:
			return None, None
		service = eServiceReference(tmp[0])
		eventId = tmp[1]
		event = self.getEventFromId(service, eventId)
		return event, service

	def connectSelectionChanged(func):
		if not self.onSelChanged.count(func):
			self.onSelChanged.append(func)

	def disconnectSelectionChanged(func):
		self.onSelChanged.remove(func)

	def selectionChanged(self):
		for x in self.onSelChanged:
			if x is not None:
				x()

	GUI_WIDGET = eListbox

	def selectionEnabled(self, enabled):
		if self.instance is not None:
			self.instance.setSelectionEnable(enabled)

	def getPixmapsForTimer(self, timer, matchType, selected=False):
		if timer is None:
			return (None, None)
		autoTimerIcon = None
		if matchType == 3:
			# recording whole event, add timer type onto pixmap lookup index
			matchType += 2 if timer.always_zap else 1 if timer.justplay else 0
			autoTimerIcon = self.icetvicon if hasattr(timer, "ice_timer_id") and timer.ice_timer_id else (self.autotimericon if timer.isAutoTimer else None)
		return self.selclocks[matchType] if selected else self.clocks[matchType], autoTimerIcon

	def queryEPG(self, list):
		try:
			return self.epgcache.lookupEvent(list)
		except:
			print("[EPGListBase] queryEPG failed\n", list)
			import traceback
			traceback.print_exc()
			return []
