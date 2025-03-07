import six

from os import system, path as os_path, remove, unlink, rename, chmod, access, X_OK
import netifaces as ni
from random import Random
from shutil import move
import string
import time

from enigma import eTimer, eConsoleAppContainer
from boxbranding import getBoxType, getMachineBrand, getMachineName, getImageType, getImageVersion

from Components.ActionMap import ActionMap, NumberActionMap, HelpableActionMap
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigIP, ConfigText, ConfigPassword, ConfigSelection, getConfigListEntry, ConfigNumber, ConfigLocations, NoSave, ConfigMacText
from Components.ConfigList import ConfigListScreen
from Components.Console import Console
from Components.FileList import MultiFileSelectList
from Components.Label import Label, MultiColorLabel
from Components.MenuList import MenuList
from Components.Network import iNetwork
from Components.OnlineUpdateCheck import feedsstatuscheck
from Components.Pixmap import Pixmap, MultiPixmap
from Components.PluginComponent import plugins
from Components.ScrollLabel import ScrollLabel
from Components.Sources.StaticText import StaticText
from Components.Sources.Boolean import Boolean
from Components.Sources.List import List
from Components.SystemInfo import SystemInfo
from Plugins.Plugin import PluginDescriptor
from Screens.HelpMenu import HelpableScreen
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.Standby import TryQuitMainloop
from Screens.TextBox import TextBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Tools.Directories import fileExists, resolveFilename, SCOPE_PLUGINS, SCOPE_CURRENT_SKIN
from Tools.LoadPixmap import LoadPixmap


# Define a function to determine whether a service is configured to
# start at boot time.
# This checks for a start file in rc2.d (rc4.d might be more
# appropriate, but historically it's been rc2.d, so...).
#
import glob


def ServiceIsEnabled(service_name):
	starter_list = glob.glob("/etc/rc2.d/S*" + service_name)
	return len(starter_list) > 0


class LogBase(TextBox):
	def __init__(self, session, filename, label="infotext"):
		self.label = label
		TextBox.__init__(self, session, label=self.label)
		self.filename = filename
		self.console = Console(binary=True)
		if not isinstance(self.skinName, list):
			self.skinName = [self.skinName]
		if "NetworkInadynLog" not in self.skinName:
			self.skinName.append("NetworkInadynLog")
		self.setTitle(_("Log"))
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self.console.ePopen("tail -n100 %s" % self.filename, self.cb)

	def cb(self, result, retval, extra_args=None):
		if retval == 0:
			self[self.label].setText(result.decode(errors="ignore"))
			self[self.label].lastPage()


# Various classes in here have common entrypoint code requirements.
# So actually make them common...
# ...but note that the exact details can depend on whether a final reboot
# is expected.
#


class NSCommon:
	def StartStopCallback(self, result=None, retval=None, extra_args=None):
		time.sleep(3)
		self.updateService()

	def removeComplete(self, result=None, retval=None, extra_args=None):
		if self.reboot_at_end:
			restartbox = self.session.openWithCallback(self.operationComplete, MessageBox,
				_('Your %s %s needs to be restarted to complete the removal of %s\nDo you want to reboot now ?') % (getMachineBrand(), getMachineName(), self.getTitle()), MessageBox.TYPE_YESNO)
			restartbox.setTitle(_("Reboot required"))
		else:
			self.operationComplete()

	def installComplete(self, result=None, retval=None, extra_args=None):
		if self.reboot_at_end:
			restartbox = self.session.openWithCallback(self.operationComplete, MessageBox,
				_('Your %s %s needs to be restarted to complete the installation of %s\nDo you want to reboot now ?') % (getMachineBrand(), getMachineName(), self.getTitle()), MessageBox.TYPE_YESNO)
			restartbox.setTitle(_("Reboot required"))
		else:
			self.message.close()

	def operationComplete(self, reboot=False):
		if reboot:
			self.session.open(TryQuitMainloop, 2)
		self.message.close()
		self.close()

	def doRemove(self, callback, pkgname):
		self.message = self.session.open(MessageBox, _("Please wait..."), MessageBox.TYPE_INFO, enable_input=False)
		self.message.setTitle(_("Removing Service"))
		self.ConsoleB.ePopen("/usr/bin/opkg remove " + pkgname + " --force-remove --autoremove", callback)

	def doInstall(self, callback, pkgname):
		self.message = self.session.open(MessageBox, _("Please wait..."), MessageBox.TYPE_INFO, enable_input=False)
		self.message.setTitle(_("Installing Service"))
		self.ConsoleB.ePopen("/usr/bin/opkg install " + pkgname, callback)

	def checkNetworkState(self, str, retval, extra_args):
		str = six.ensure_str(str)
		if "Collected errors" in str:
			self.session.openWithCallback(self.close, MessageBox, _("A background update check is in progress, please wait a few minutes and then try again."), type=MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
		elif not str:
			if (getImageType() != "release" and feedsstatuscheck.getFeedsBool() not in ("unknown", "alien", "developer")) or (getImageType() == "release" and feedsstatuscheck.getFeedsBool() not in ("stable", "unstable", "alien", "developer")):
				self.session.openWithCallback(self.InstallPackageFailed, MessageBox, feedsstatuscheck.getFeedsErrorMessage(), type=MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			else:
				mtext = _("Are you ready to install %s ?") % self.getTitle()
				self.session.openWithCallback(self.InstallPackage, MessageBox, mtext, MessageBox.TYPE_YESNO)
		else:
			self.updateService()

	def UninstallCheck(self):
		self.ConsoleB.ePopen("/usr/bin/opkg list_installed " + self.service_name, self.RemovedataAvail)

	def RemovedataAvail(self, result, retval, extra_args):
		if result:
			self.session.openWithCallback(self.RemovePackage, MessageBox, _("Are you ready to remove %s ?") % self.getTitle(), MessageBox.TYPE_YESNO)
		else:
			self.updateService()

	def RemovePackage(self, val):
		if val:
			self.doRemove(self.removeComplete, self.service_name)

	def InstallPackage(self, val):
		if val:
			self.doInstall(self.installComplete, self.service_name)
		else:
			self.close()

	def InstallPackageFailed(self, val):
		self.close()

	def InstallCheck(self):
		self.Console.ePopen("/usr/bin/opkg list_installed " + self.service_name, self.checkNetworkState)

	def createSummary(self):
		return NetworkServicesSummary


class NetworkAdapterSelection(Screen, HelpableScreen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.setTitle(_("Device"))

		self.wlan_errortext = _("No working wireless network adapter found.\nPlease verify that you have attached a compatible WLAN device and your network is configured correctly.")
		self.lan_errortext = _("No working local network adapter found.\nPlease verify that you have attached a network cable and your network is configured correctly.")
		self.oktext = _("Press OK on your remote control to continue.")
		self.edittext = _("Press OK to edit the settings.")
		self.defaulttext = _("Press yellow to set this interface as the default interface.")
		self.restartLanRef = None

		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Select"))
		self["key_yellow"] = StaticText("")
		self["key_blue"] = StaticText("")
		self["introduction"] = StaticText(self.edittext)

		self["OkCancelActions"] = HelpableActionMap(self, "OkCancelActions",
			{
			"cancel": (self.close, _("Exit network interface list")),
			"ok": (self.okbuttonClick, _("Select interface")),
			})

		self["ColorActions"] = HelpableActionMap(self, "ColorActions",
			{
			"red": (self.close, _("Exit network interface list")),
			"green": (self.okbuttonClick, _("Select interface")),
			"blue": (self.openNetworkWizard, _("Use the network wizard to configure selected network adapter")),
			})

		self["DefaultInterfaceAction"] = HelpableActionMap(self, "ColorActions",
			{
			"yellow": (self.setDefaultInterface, [_("Set interface as the default Interface"), _("* Only available if more than one interface is active.")]),
			})

		self.adapters = [(iNetwork.getFriendlyAdapterName(x), x) for x in iNetwork.getAdapterList()]

		if not self.adapters:
			self.adapters = [(iNetwork.getFriendlyAdapterName(x), x) for x in iNetwork.getConfiguredAdapters()]

		if len(self.adapters) == 0:
			self.adapters = [(iNetwork.getFriendlyAdapterName(x), x) for x in iNetwork.getInstalledAdapters()]

		self.onChangedEntry = []
		self.list = []
		self["list"] = List(self.list)
		self.updateList()
		if not self.selectionChanged in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

		if len(self.adapters) == 1:
			self.onFirstExecBegin.append(self.okbuttonClick)
		self.onClose.append(self.cleanup)

	def createSummary(self):
		from Screens.PluginBrowser import PluginBrowserSummary
		return PluginBrowserSummary

	def selectionChanged(self):
		item = self["list"].getCurrent()
		if item:
			name = item[0]
			desc = item[1]
		else:
			name = ""
			desc = ""
		for cb in self.onChangedEntry:
			cb(name, desc)

	def buildInterfaceList(self, iface, name, default, active):
		divpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "div-h.png"))
		defaultpng = None
		activepng = None
		description = None
		interfacepng = None

		if not iNetwork.isWirelessInterface(iface):
			if active == True:
				interfacepng = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/network_wired-active.png"))
			elif active is False:
				interfacepng = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/network_wired-inactive.png"))
			else:
				interfacepng = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/network_wired.png"))
		elif iNetwork.isWirelessInterface(iface):
			if active == True:
				interfacepng = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/network_wireless-active.png"))
			elif active is False:
				interfacepng = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/network_wireless-inactive.png"))
			else:
				interfacepng = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/network_wireless.png"))

		num_configured_if = len(iNetwork.getConfiguredAdapters())
		if num_configured_if >= 2:
			if default is True:
				defaultpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "buttons/button_blue.png"))
			elif default is False:
				defaultpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "buttons/button_blue_off.png"))
		if active is True:
			activepng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "icons/lock_on.png"))
		elif active is False:
			activepng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "icons/lock_error.png"))

		description = iNetwork.getFriendlyAdapterDescription(iface)

		return iface, name, description, interfacepng, defaultpng, activepng, divpng

	def updateList(self):
		self.list = []
		default_gw = None
		num_configured_if = len(iNetwork.getConfiguredAdapters())
		if num_configured_if >= 2:
			self["key_yellow"].setText(_("Default"))
			self["introduction"].setText(self.defaulttext)
			self["DefaultInterfaceAction"].setEnabled(True)
		else:
			self["key_yellow"].setText("")
			self["introduction"].setText(self.edittext)
			self["DefaultInterfaceAction"].setEnabled(False)

		if num_configured_if < 2 and os_path.exists("/etc/default_gw"):
			unlink("/etc/default_gw")

		if os_path.exists("/etc/default_gw"):
			fp = open("/etc/default_gw", "r")
			result = fp.read()
			fp.close()
			default_gw = result

		for x in self.adapters:
			if x[1] == default_gw:
				default_int = True
			else:
				default_int = False
			if iNetwork.getAdapterAttribute(x[1], "up") == True:
				active_int = True
			else:
				active_int = False
			self.list.append(self.buildInterfaceList(x[1], _(x[0]), default_int, active_int))

		if os_path.exists(resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkWizard/networkwizard.xml")):
			self["key_blue"].setText(_("Network wizard"))
		self["list"].list = self.list

	def setDefaultInterface(self):
		selection = self["list"].getCurrent()
		num_if = len(self.list)
		old_default_gw = None
		num_configured_if = len(iNetwork.getConfiguredAdapters())
		if os_path.exists("/etc/default_gw"):
			fp = open("/etc/default_gw", "r")
			old_default_gw = fp.read()
			fp.close()
		if num_configured_if > 1 and (not old_default_gw or old_default_gw != selection[0]):
			fp = open("/etc/default_gw", "w+")
			fp.write(selection[0])
			fp.close()
			self.restartLan()
		elif old_default_gw and num_configured_if < 2:
			unlink("/etc/default_gw")
			self.restartLan()

	def okbuttonClick(self):
		selection = self["list"].getCurrent()
		if selection is not None:
			self.session.openWithCallback(self.AdapterSetupClosed, AdapterSetupConfiguration, selection[0])

	def AdapterSetupClosed(self, *ret):
		if len(self.adapters) == 1:
			self.close()
		else:
			self.updateList()

	def cleanup(self):
		iNetwork.stopLinkStateConsole()
		iNetwork.stopRestartConsole()
		iNetwork.stopGetInterfacesConsole()

	def restartLan(self):
		iNetwork.restartNetwork(self.restartLanDataAvail)
		self.restartLanRef = self.session.openWithCallback(self.restartfinishedCB, MessageBox, _("Please wait while we configure your network..."), type=MessageBox.TYPE_INFO, enable_input=False)

	def restartLanDataAvail(self, data):
		if data == True:
			iNetwork.getInterfaces(self.getInterfacesDataAvail)

	def getInterfacesDataAvail(self, data):
		if data == True:
			self.restartLanRef.close(True)

	def restartfinishedCB(self, data):
		if data == True:
			self.updateList()
			self.session.open(MessageBox, _("Finished configuring your network"), type=MessageBox.TYPE_INFO, timeout=10, default=False)

	def openNetworkWizard(self):
		if os_path.exists(resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkWizard/networkwizard.xml")):
			try:
				from Plugins.SystemPlugins.NetworkWizard.NetworkWizard import NetworkWizard
			except ImportError:
				self.session.open(MessageBox, _("The network wizard extension is not installed!\nPlease install it."), type=MessageBox.TYPE_INFO, timeout=10)
			else:
				selection = self["list"].getCurrent()
				if selection is not None:
					self.session.openWithCallback(self.AdapterSetupClosed, NetworkWizard, selection[0])


class NameserverSetup(ConfigListScreen, HelpableScreen, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.setTitle(_("Nameserver Settings"))
		self.skinName = ["NameserverSetup", "Setup"]
		self.backupNameserverList = iNetwork.getNameserverList()[:]
		print("[NameserverSetup] backup-list:%s" % self.backupNameserverList)
		self["key_yellow"] = StaticText(_("Add"))
		self["key_blue"] = StaticText(_("Delete"))

		self["actions"] = HelpableActionMap(self, ["ColorActions"],
			{
			"yellow": (self.add, _("Add a nameserver entry")),
			"blue": (self.remove, _("Remove a nameserver entry")),
			})
		ConfigListScreen.__init__(self, [], session=session, on_change=self.changedEntry, fullUI=True)
		self.createConfig()
		self.createSetup()

	def createConfig(self):
		self.nameservers = iNetwork.getNameserverList()
		self.nameserverEntries = [NoSave(ConfigIP(default=nameserver)) for nameserver in self.nameservers]

	def createSetup(self):
		self["config"].list = [getConfigListEntry(_("Nameserver %d") % (i + 1), x) for i, x in enumerate(self.nameserverEntries)]

	def keySave(self):
		iNetwork.clearNameservers()
		for nameserver in self.nameserverEntries:
			iNetwork.addNameserver(nameserver.value)
		iNetwork.writeNameserverConfig()
		self.close()

	def run(self):
		self.keySave()

	def keyCancel(self):
		iNetwork.clearNameservers()
		print("[NameserverSetup] backup-list:%s" % self.backupNameserverList)
		for nameserver in self.backupNameserverList:
			iNetwork.addNameserver(nameserver)
		self.close()

	def add(self):
		iNetwork.addNameserver([0, 0, 0, 0])
		self.createConfig()
		self.createSetup()

	def remove(self):
		print("[NameserverSetup] currentIndex:%s" % self["config"].getCurrentIndex())
		index = self["config"].getCurrentIndex()
		if index < len(self.nameservers):
			iNetwork.removeNameserver(self.nameservers[index])
			self.createConfig()
			self.createSetup()


class NetworkMacSetup(ConfigListScreen, HelpableScreen, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.skinName = ["NetworkMacSetup", "Setup"]
		self.setTitle(_("MAC Address Settings"))
		ifacex = "wlan0"
		ifacey = "wlan3"
		if iNetwork.getAdapterAttribute(ifacex, "up"):
			self.mode = ifacex
			self.curMac = self.getmac(ifacex)
		elif iNetwork.getAdapterAttribute(ifacey, "up"):
			self.mode = ifacey
			self.curMac = self.getmac(ifacey)
		else:
			self.mode = "eth0"
			self.curMac = self.getmac("eth0")
		# print("[NetworkSetup]self.mode=, MacWiFiLan=", self.mode, "   ", self.curMac)
		if self.curMac:
			self.getConfigMac = NoSave(ConfigMacText(default=self.curMac))

		ConfigListScreen.__init__(self, [], session=session, on_change=self.changedEntry, fullUI=True)
		self.createSetup()

	def getmac(self, iface):
		nit = ni.ifaddresses(iface)
		return nit[ni.AF_LINK][0]['addr']

	def createSetup(self):
		self["config"].list = [getConfigListEntry(_("MAC address"), self.getConfigMac) if self.curMac else (_("No MAC interface found"),)]

	def keySave(self):
		if self.curMac:
			if self.mode in ("wlan0", "wlan3"):
				iNetwork.resetWiFiMac(Mac=self.getConfigMac.value, wlan=self.mode)
			else:
				f = open("/etc/enigma2/hwmac", "w")
				f.write(self.getConfigMac.value)
				f.close()
			self.restartLan()

	def run(self):
		self.keySave()

	def restartLan(self):
		iNetwork.restartNetwork(self.restartLanDataAvail)
		self.restartLanRef = self.session.openWithCallback(self.restartfinishedCB, MessageBox, _("Please wait while we configure your network..."), type=MessageBox.TYPE_INFO, enable_input=False)

	def restartLanDataAvail(self, data):
		if data == True:
			iNetwork.getInterfaces(self.getInterfacesDataAvail)

	def getInterfacesDataAvail(self, data):
		if data == True:
			self.restartLanRef.close(True)

	def restartfinishedCB(self, data):
		if data == True:
			self.session.openWithCallback(self.close, MessageBox, _("Finished configuring your network"), type=MessageBox.TYPE_INFO, timeout=10, default=False)


class AdapterSetup(ConfigListScreen, HelpableScreen, Screen):
	def __init__(self, session, networkinfo=None, essid=None):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)

		if isinstance(networkinfo, (list, tuple)):
			self.iface = networkinfo[0]
			self.essid = networkinfo[1]
		else:
			self.iface = networkinfo
			self.essid = essid

		self.setTitle(_("Adapter Settings"))

		self.extended = None
		self.applyConfigRef = None
		self.finished_cb = None
		self.oktext = _("Press OK on your remote control to continue.")
		self.oldInterfaceState = iNetwork.getAdapterAttribute(self.iface, "up")

		self.createConfig()

		self["ColorActions"] = HelpableActionMap(self, "ColorActions",
			{
			"blue": (self.KeyBlue, _("Open nameserver configuration")),
			})

		ConfigListScreen.__init__(self, [], session=session, on_change=self.newConfig, fullUI=True)

		self.createSetup()
		self.onLayoutFinish.append(self.layoutFinished)
		self.onClose.append(self.cleanup)

		self["DNS1text"] = StaticText(_("Primary DNS"))
		self["DNS2text"] = StaticText(_("Secondary DNS"))
		self["DNS1"] = StaticText()
		self["DNS2"] = StaticText()
		self["introduction"] = StaticText(_("Current settings:"))

		self["IPtext"] = StaticText(_("IP address"))
		self["Netmasktext"] = StaticText(_("Subnet"))
		self["Gatewaytext"] = StaticText(_("Gateway"))

		self["IP"] = StaticText()
		self["Mask"] = StaticText()
		self["Gateway"] = StaticText()

		self["Adaptertext"] = StaticText(_("Network:"))
		self["Adapter"] = StaticText()
		self["introduction2"] = StaticText(_("Press OK to activate the settings."))
		self["key_blue"] = StaticText(_("Edit DNS"))

	def layoutFinished(self):
		self["DNS1"].setText(self.primaryDNS.getText())
		self["DNS2"].setText(self.secondaryDNS.getText())
		if self.ipConfigEntry.getText() is not None:
			if self.ipConfigEntry.getText() == "0.0.0.0":
				self["IP"].setText(_("N/A"))
			else:
				self["IP"].setText(self.ipConfigEntry.getText())
		else:
			self["IP"].setText(_("N/A"))
		if self.netmaskConfigEntry.getText() is not None:
			if self.netmaskConfigEntry.getText() == "0.0.0.0":
				self["Mask"].setText(_("N/A"))
			else:
				self["Mask"].setText(self.netmaskConfigEntry.getText())
		else:
			self["IP"].setText(_("N/A"))
		if iNetwork.getAdapterAttribute(self.iface, "gateway"):
			if self.gatewayConfigEntry.getText() == "0.0.0.0":
				self["Gatewaytext"].setText(_("Gateway"))
				self["Gateway"].setText(_("N/A"))
			else:
				self["Gatewaytext"].setText(_("Gateway"))
				self["Gateway"].setText(self.gatewayConfigEntry.getText())
		else:
			self["Gateway"].setText("")
			self["Gatewaytext"].setText("")
		self["Adapter"].setText(iNetwork.getFriendlyAdapterName(self.iface))

	def createConfig(self):
		self.InterfaceEntry = None
		self.dhcpEntry = None
		self.gatewayEntry = None
		self.hiddenSSID = None
		self.wlanSSID = None
		self.encryption = None
		self.encryptionType = None
		self.encryptionKey = None
		self.encryptionlist = None
		self.weplist = None
		self.wsconfig = None
		self.default = None

		if iNetwork.isWirelessInterface(self.iface):
			driver = iNetwork.detectWlanModule(self.iface)
			if driver in ("brcm-wl", ):
				from Plugins.SystemPlugins.WirelessLan.Wlan import brcmWLConfig
				self.ws = brcmWLConfig()
			else:
				from Plugins.SystemPlugins.WirelessLan.Wlan import wpaSupplicant
				self.ws = wpaSupplicant()
			self.encryptionlist = []
			self.encryptionlist.append(("Unencrypted", _("Unencrypted")))
			self.encryptionlist.append(("WEP", _("WEP")))
			self.encryptionlist.append(("WPA", _("WPA")))
			if not os_path.exists("/tmp/bcm/" + self.iface):
				self.encryptionlist.append(("WPA/WPA2", _("WPA or WPA2")))
			self.encryptionlist.append(("WPA2", _("WPA2")))
			self.weplist = []
			self.weplist.append("ASCII")
			self.weplist.append("HEX")

			self.wsconfig = self.ws.loadConfig(self.iface)
			if self.essid is None:
				self.essid = self.wsconfig["ssid"]

			config.plugins.wlan.hiddenessid = NoSave(ConfigYesNo(default=self.wsconfig["hiddenessid"]))
			config.plugins.wlan.essid = NoSave(ConfigText(default=self.essid, visible_width=50, fixed_size=False))
			config.plugins.wlan.encryption = NoSave(ConfigSelection(self.encryptionlist, default=self.wsconfig["encryption"]))
			config.plugins.wlan.wepkeytype = NoSave(ConfigSelection(self.weplist, default=self.wsconfig["wepkeytype"]))
			config.plugins.wlan.psk = NoSave(ConfigPassword(default=self.wsconfig["key"], visible_width=50, fixed_size=False))

		self.activateInterfaceEntry = NoSave(ConfigYesNo(default=iNetwork.getAdapterAttribute(self.iface, "up") or False))
		self.dhcpConfigEntry = NoSave(ConfigYesNo(default=iNetwork.getAdapterAttribute(self.iface, "dhcp") or False))
		self.ipConfigEntry = NoSave(ConfigIP(default=iNetwork.getAdapterAttribute(self.iface, "ip")) or [0, 0, 0, 0])
		self.netmaskConfigEntry = NoSave(ConfigIP(default=iNetwork.getAdapterAttribute(self.iface, "netmask") or [255, 0, 0, 0]))
		if iNetwork.getAdapterAttribute(self.iface, "gateway"):
			self.dhcpdefault = True
		else:
			self.dhcpdefault = False
		self.hasGatewayConfigEntry = NoSave(ConfigYesNo(default=self.dhcpdefault or False))
		self.gatewayConfigEntry = NoSave(ConfigIP(default=iNetwork.getAdapterAttribute(self.iface, "gateway") or [0, 0, 0, 0]))
		nameserver = (iNetwork.getNameserverList() + [[0, 0, 0, 0]] * 2)[0:2]
		self.primaryDNS = NoSave(ConfigIP(default=nameserver[0]))
		self.secondaryDNS = NoSave(ConfigIP(default=nameserver[1]))

	def createSetup(self):
		self.list = []
		self.InterfaceEntry = getConfigListEntry(_("Use interface"), self.activateInterfaceEntry)

		self.list.append(self.InterfaceEntry)
		if self.activateInterfaceEntry.value:
			self.dhcpEntry = getConfigListEntry(_("Use DHCP"), self.dhcpConfigEntry)
			self.list.append(self.dhcpEntry)
			if not self.dhcpConfigEntry.value:
				self.list.append(getConfigListEntry(_("IP address"), self.ipConfigEntry))
				self.list.append(getConfigListEntry(_("Netmask"), self.netmaskConfigEntry))
				self.gatewayEntry = getConfigListEntry(_("Use a gateway"), self.hasGatewayConfigEntry)
				self.list.append(self.gatewayEntry)
				if self.hasGatewayConfigEntry.value:
					self.list.append(getConfigListEntry(_("Gateway"), self.gatewayConfigEntry))

			self.extended = None
			self.configStrings = None
			for p in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKSETUP):
				callFnc = p.fnc["ifaceSupported"](self.iface)
				if callFnc is not None:
					if "WlanPluginEntry" in p.fnc:  # internally used only for WLAN Plugin
						self.extended = callFnc
						if "configStrings" in p.fnc:
							self.configStrings = p.fnc["configStrings"]

						isExistBcmWifi = os_path.exists("/tmp/bcm/" + self.iface)
						if not isExistBcmWifi:
							self.hiddenSSID = getConfigListEntry(_("Hidden network"), config.plugins.wlan.hiddenessid)
							self.list.append(self.hiddenSSID)
						self.wlanSSID = getConfigListEntry(_("Network name (SSID)"), config.plugins.wlan.essid)
						self.list.append(self.wlanSSID)
						self.encryption = getConfigListEntry(_("Encryption"), config.plugins.wlan.encryption)
						self.list.append(self.encryption)
						if not isExistBcmWifi:
							self.encryptionType = getConfigListEntry(_("Encryption key type"), config.plugins.wlan.wepkeytype)
						self.encryptionKey = getConfigListEntry(_("Encryption key"), config.plugins.wlan.psk)

						if config.plugins.wlan.encryption.value != "Unencrypted":
							if config.plugins.wlan.encryption.value == "WEP":
								if not isExistBcmWifi:
									self.list.append(self.encryptionType)
							self.list.append(self.encryptionKey)
		self["config"].list = self.list

	def KeyBlue(self):
		self.session.openWithCallback(self.NameserverSetupClosed, NameserverSetup)

	def newConfig(self):
		if self["config"].getCurrent() == self.InterfaceEntry:
			self.createSetup()
		if self["config"].getCurrent() == self.dhcpEntry:
			self.createSetup()
		if self["config"].getCurrent() == self.gatewayEntry:
			self.createSetup()
		if iNetwork.isWirelessInterface(self.iface):
			if self["config"].getCurrent() == self.encryption:
				self.createSetup()
		ConfigListScreen.changedEntry(self)

	def keySave(self):
		self.hideInputHelp()
		if self["config"].isChanged():
			self.session.openWithCallback(self.keySaveConfirm, MessageBox, (_("Are you sure you want to activate this network configuration?\n\n") + self.oktext))
		else:
			if self.finished_cb:
				self.finished_cb()
			else:
				self.close("cancel")
		config.network.save()

	def keySaveConfirm(self, ret=False):
		if ret == True:
			num_configured_if = len(iNetwork.getConfiguredAdapters())
			if num_configured_if >= 1:
				if self.iface in iNetwork.getConfiguredAdapters():
					self.applyConfig(True)
				else:
					self.session.openWithCallback(self.secondIfaceFoundCB, MessageBox, _("A second configured interface has been found.\n\nDo you want to disable the second network interface?"), default=True)
			else:
				self.applyConfig(True)
		else:
			self.keyCancel()

	def secondIfaceFoundCB(self, data):
		if data == False:
			self.applyConfig(True)
		else:
			configuredInterfaces = iNetwork.getConfiguredAdapters()
			for interface in configuredInterfaces:
				if interface == self.iface:
					continue
				iNetwork.setAdapterAttribute(interface, "up", False)
			iNetwork.deactivateInterface(configuredInterfaces, self.deactivateSecondInterfaceCB)

	def deactivateSecondInterfaceCB(self, data):
		if data == True:
			self.applyConfig(True)

	def applyConfig(self, ret=False):
		if ret == True:
			self.applyConfigRef = None
			iNetwork.setAdapterAttribute(self.iface, "up", self.activateInterfaceEntry.value)
			iNetwork.setAdapterAttribute(self.iface, "dhcp", self.dhcpConfigEntry.value)
			iNetwork.setAdapterAttribute(self.iface, "ip", self.ipConfigEntry.value)
			iNetwork.setAdapterAttribute(self.iface, "netmask", self.netmaskConfigEntry.value)
			if self.hasGatewayConfigEntry.value:
				iNetwork.setAdapterAttribute(self.iface, "gateway", self.gatewayConfigEntry.value)
			else:
				iNetwork.removeAdapterAttribute(self.iface, "gateway")

			if self.extended is not None and self.configStrings is not None:
				iNetwork.setAdapterAttribute(self.iface, "configStrings", self.configStrings(self.iface))
				self.ws.writeConfig(self.iface)

			if self.activateInterfaceEntry.value == False:
				iNetwork.deactivateInterface(self.iface, self.deactivateInterfaceCB)
				iNetwork.writeNetworkConfig()
				self.applyConfigRef = self.session.openWithCallback(self.applyConfigfinishedCB, MessageBox, _("Please wait while your network configuration is activated..."), type=MessageBox.TYPE_INFO, enable_input=False)
			else:
				if self.oldInterfaceState == False:
					iNetwork.activateInterface(self.iface, self.deactivateInterfaceCB)
				else:
					iNetwork.deactivateInterface(self.iface, self.activateInterfaceCB)
				iNetwork.writeNetworkConfig()
				self.applyConfigRef = self.session.openWithCallback(self.applyConfigfinishedCB, MessageBox, _("Please wait while your network configuration is activated..."), type=MessageBox.TYPE_INFO, enable_input=False)
		else:
			self.keyCancel()

	def deactivateInterfaceCB(self, data):
		if data == True:
			self.applyConfigDataAvail(True)

	def activateInterfaceCB(self, data):
		if data == True:
			iNetwork.activateInterface(self.iface, self.applyConfigDataAvail)

	def applyConfigDataAvail(self, data):
		if data == True:
			iNetwork.getInterfaces(self.getInterfacesDataAvail)

	def getInterfacesDataAvail(self, data):
		if data == True:
			self.applyConfigRef.close(True)

	def applyConfigfinishedCB(self, data):
		if data == True:
			if self.finished_cb:
				self.session.openWithCallback(lambda x: self.finished_cb(), MessageBox, _("Your network configuration has been activated."), type=MessageBox.TYPE_INFO, timeout=10)
			else:
				self.session.openWithCallback(self.ConfigfinishedCB, MessageBox, _("Your network configuration has been activated."), type=MessageBox.TYPE_INFO, timeout=10)

	def ConfigfinishedCB(self, data):
		if data is not None:
			if data == True:
				self.close("ok")

	def keyCancelConfirm(self, result):
		if not result:
			return
		if self.oldInterfaceState == False:
			iNetwork.deactivateInterface(self.iface, self.keyCancelCB)
		else:
			self.close("cancel")

	def keyCancel(self):
		self.hideInputHelp()
		if self["config"].isChanged():
			self.session.openWithCallback(self.keyCancelConfirm, MessageBox, _("Really close without saving settings?"), default=False)
		else:
			self.close("cancel")

	def keyCancelCB(self, data):
		if data is not None:
			if data == True:
				self.close("cancel")

	def runAsync(self, finished_cb):
		self.finished_cb = finished_cb
		self.keySave()

	def NameserverSetupClosed(self, *ret):
		iNetwork.loadNameserverConfig()
		nameserver = (iNetwork.getNameserverList() + [[0, 0, 0, 0]] * 2)[0:2]
		self.primaryDNS = NoSave(ConfigIP(default=nameserver[0]))
		self.secondaryDNS = NoSave(ConfigIP(default=nameserver[1]))
		self.createSetup()
		self.layoutFinished()

	def cleanup(self):
		iNetwork.stopLinkStateConsole()

	def hideInputHelp(self):
		current = self["config"].getCurrent()
		if current == self.wlanSSID:
			if current[1].help_window.instance is not None:
				current[1].help_window.instance.hide()
		elif current == self.encryptionKey and config.plugins.wlan.encryption.value != "Unencrypted":
			if current[1].help_window.instance is not None:
				current[1].help_window.instance.hide()


class AdapterSetupConfiguration(Screen, HelpableScreen):
	def __init__(self, session, iface=None):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.setTitle(_("Network Setup"))

		self.session = session
		self.iface = iface
		self.restartLanRef = None
		self.LinkState = None
		self.onChangedEntry = []
		self.mainmenu = ""
		self["menulist"] = MenuList(self.mainmenu)
		self["key_red"] = StaticText(_("Close"))
		self["description"] = StaticText()
		self["IFtext"] = StaticText()
		self["IF"] = StaticText()
		self["Statustext"] = StaticText()
		self["statuspic"] = MultiPixmap()
		self["statuspic"].hide()
		self["devicepic"] = MultiPixmap()

		self.oktext = _("Press OK on your remote control to continue.")
		self.reboottext = _("Your STB will restart after pressing OK on your remote control.")
		self.errortext = _("No working wireless network interface found.\n Please verify that you have attached a compatible WLAN device or enable your local network interface.")
		self.missingwlanplugintxt = _("The wireless LAN plugin is not installed!\nPlease install it.")

		self["WizardActions"] = HelpableActionMap(self, "WizardActions",
			{
			"up": (self.up, _("Move up to previous entry")),
			"down": (self.down, _("Move down to next entry")),
			"left": (self.left, _("Move up to first entry")),
			"right": (self.right, _("Move down to last entry")),
			})

		self["OkCancelActions"] = HelpableActionMap(self, "OkCancelActions",
			{
			"cancel": (self.close, _("Exit network adapter setup menu")),
			"ok": (self.ok, _("Select menu entry")),
			})

		self["ColorActions"] = HelpableActionMap(self, "ColorActions",
			{
			"red": (self.close, _("Exit network adapter setup menu")),
			})

		self["actions"] = NumberActionMap(["WizardActions", "ShortcutActions"],
		{
			"ok": self.ok,
			"back": self.close,
			"up": self.up,
			"down": self.down,
			"red": self.close,
			"left": self.left,
			"right": self.right,
		}, -2)

		self.updateStatusbar()
		self.onClose.append(self.cleanup)
		if not self.selectionChanged in self["menulist"].onSelectionChanged:
			self["menulist"].onSelectionChanged.append(self.selectionChanged)
		self.selectionChanged()
		self.onLayoutFinish.append(self.updateStatusbar)

	def queryWirelessDevice(self, iface):
		try:
			from wifi.scan import Cell
			import errno
		except ImportError:
			return False
		else:
			try:
				system("ifconfig %s up" % iface)
				wlanresponse = list(Cell.all(iface))
			except IOError as err:
				error_no, error_str = err.args
				if error_no in (errno.EOPNOTSUPP, errno.ENODEV, errno.EPERM):
					return False
				else:
					print("[AdapterSetupConfiguration] error: ", error_no, error_str)
					return True
			else:
				return True

	def ok(self):
		self.cleanup()
		if self["menulist"].getCurrent()[1] == "edit":
			if iNetwork.isWirelessInterface(self.iface):
				try:
					from Plugins.SystemPlugins.WirelessLan.plugin import WlanScan
				except ImportError:
					self.session.open(MessageBox, self.missingwlanplugintxt, type=MessageBox.TYPE_INFO, timeout=10)
				else:
					if self.queryWirelessDevice(self.iface):
						self.session.openWithCallback(self.AdapterSetupClosed, AdapterSetup, self.iface)
					else:
						self.showErrorMessage()  # Display Wlan not available Message
			else:
				self.session.openWithCallback(self.AdapterSetupClosed, AdapterSetup, self.iface)
		if self["menulist"].getCurrent()[1] == "test":
			self.session.open(NetworkAdapterTest, self.iface)
		if self["menulist"].getCurrent()[1] == "dns":
			self.session.open(NameserverSetup)
		if self["menulist"].getCurrent()[1] == 'mac':
			self.session.open(NetworkMacSetup)
		if self["menulist"].getCurrent()[1] == "scanwlan":
			try:
				from Plugins.SystemPlugins.WirelessLan.plugin import WlanScan
			except ImportError:
				self.session.open(MessageBox, self.missingwlanplugintxt, type=MessageBox.TYPE_INFO, timeout=10)
			else:
				if self.queryWirelessDevice(self.iface):
					self.session.openWithCallback(self.WlanScanClosed, WlanScan, self.iface)
				else:
					self.showErrorMessage()  # Display Wlan not available Message
		if self["menulist"].getCurrent()[1] == "wlanstatus":
			try:
				from Plugins.SystemPlugins.WirelessLan.plugin import WlanStatus
			except ImportError:
				self.session.open(MessageBox, self.missingwlanplugintxt, type=MessageBox.TYPE_INFO, timeout=10)
			else:
				if self.queryWirelessDevice(self.iface):
					self.session.openWithCallback(self.WlanStatusClosed, WlanStatus, self.iface)
				else:
					self.showErrorMessage()  # Display Wlan not available Message
		if self["menulist"].getCurrent()[1] == "lanrestart":
			self.session.openWithCallback(self.restartLan, MessageBox, (_("Are you sure you want to restart your network interfaces?\n\n") + self.oktext))
		if self["menulist"].getCurrent()[1] == "openwizard":
			from Plugins.SystemPlugins.NetworkWizard.NetworkWizard import NetworkWizard
			self.session.openWithCallback(self.AdapterSetupClosed, NetworkWizard, self.iface)
		if self["menulist"].getCurrent()[1][0] == "extendedSetup":
			self.extended = self["menulist"].getCurrent()[1][2]
			self.extended(self.session, self.iface)

	def up(self):
		self["menulist"].up()

	def down(self):
		self["menulist"].down()

	def left(self):
		self["menulist"].pageUp()

	def right(self):
		self["menulist"].pageDown()

	def createSummary(self):
		from Screens.PluginBrowser import PluginBrowserSummary
		return PluginBrowserSummary

	def selectionChanged(self):
		if self["menulist"].getCurrent()[1] == "edit":
			self["description"].setText(_("Edit the network configuration of your %s %s.\n") % (getMachineBrand(), getMachineName()) + self.oktext)
		if self["menulist"].getCurrent()[1] == "test":
			self["description"].setText(_("Test the network configuration of your %s %s.\n") % (getMachineBrand(), getMachineName()) + self.oktext)
		if self["menulist"].getCurrent()[1] == "dns":
			self["description"].setText(_("Edit the Nameserver configuration of your %s %s.\n") % (getMachineBrand(), getMachineName()) + self.oktext)
		if self["menulist"].getCurrent()[1] == "scanwlan":
			self["description"].setText(_("Scan your network for wireless access points and connect to them using your selected wireless device.\n") + self.oktext)
		if self["menulist"].getCurrent()[1] == "wlanstatus":
			self["description"].setText(_("Shows the state of your wireless LAN connection.\n") + self.oktext)
		if self["menulist"].getCurrent()[1] == "lanrestart":
			self["description"].setText(_("Restart your network connection and interfaces.\n") + self.oktext)
		if self["menulist"].getCurrent()[1] == "openwizard":
			self["description"].setText(_("Use the network wizard to configure your Network\n") + self.oktext)
		if self["menulist"].getCurrent()[1][0] == "extendedSetup":
			self["description"].setText(_(self["menulist"].getCurrent()[1][1]) + self.oktext)
		if self["menulist"].getCurrent()[1] == "mac":
			self["description"].setText(_("Set the MAC address of your %s %s.\n") % (getMachineBrand(), getMachineName()) + self.oktext)
		item = self["menulist"].getCurrent()
		if item:
			name = str(self["menulist"].getCurrent()[0])
			desc = self["description"].text
		else:
			name = ""
			desc = ""
		for cb in self.onChangedEntry:
			cb(name, desc)

	def updateStatusbar(self, data=None):
		self.mainmenu = self.genMainMenu()
		self["menulist"].l.setList(self.mainmenu)
		self["IFtext"].setText(_("Network:"))
		self["IF"].setText(iNetwork.getFriendlyAdapterName(self.iface))
		self["Statustext"].setText(_("Link:"))

		if iNetwork.isWirelessInterface(self.iface):
			self["devicepic"].setPixmapNum(1)
			try:
				from Plugins.SystemPlugins.WirelessLan.Wlan import iStatus
			except:
				self["statuspic"].setPixmapNum(1)
				self["statuspic"].show()
			else:
				iStatus.getDataForInterface(self.iface, self.getInfoCB)
		else:
			iNetwork.getLinkState(self.iface, self.dataAvail)
			self["devicepic"].setPixmapNum(0)
		self["devicepic"].show()

	def doNothing(self):
		pass

	def genMainMenu(self):
		menu = [(_("Adapter settings"), "edit"), (_("Nameserver settings"), "dns"), (_("Network test"), "test"), (_("Restart network"), "lanrestart")]

		self.extended = None
		self.extendedSetup = None
		for p in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKSETUP):
			callFnc = p.fnc["ifaceSupported"](self.iface)
			if callFnc is not None:
				self.extended = callFnc
				if "WlanPluginEntry" in p.fnc:  # internally used only for WLAN Plugin
					menu.append((_("Scan wireless networks"), "scanwlan"))
					if iNetwork.getAdapterAttribute(self.iface, "up"):
						menu.append((_("Show WLAN status"), "wlanstatus"))
				else:
					if "menuEntryName" in p.fnc:
						menuEntryName = p.fnc["menuEntryName"](self.iface)
					else:
						menuEntryName = _("Extended setup...")
					if "menuEntryDescription" in p.fnc:
						menuEntryDescription = p.fnc["menuEntryDescription"](self.iface)
					else:
						menuEntryDescription = _("Extended network setup plugin...")
					self.extendedSetup = ("extendedSetup", menuEntryDescription, self.extended)
					menu.append((menuEntryName, self.extendedSetup))

		if os_path.exists(resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkWizard/networkwizard.xml")):
			menu.append((_("Network wizard"), "openwizard"))
#		kernel_ver = about.getKernelVersionString()
#		if kernel_ver <= "3.5.0":
		menu.append((_("Network MAC settings"), "mac"))
		return menu

	def AdapterSetupClosed(self, *ret):
		if ret is not None and len(ret):
			if ret[0] == "ok" and (iNetwork.isWirelessInterface(self.iface) and iNetwork.getAdapterAttribute(self.iface, "up") == True):
				try:
					from Plugins.SystemPlugins.WirelessLan.plugin import WlanStatus
				except ImportError:
					self.session.open(MessageBox, self.missingwlanplugintxt, type=MessageBox.TYPE_INFO, timeout=10)
				else:
					if self.queryWirelessDevice(self.iface):
						self.session.openWithCallback(self.WlanStatusClosed, WlanStatus, self.iface)
					else:
						self.showErrorMessage()  # Display Wlan not available Message
			else:
				self.updateStatusbar()
		else:
			self.updateStatusbar()

	def WlanStatusClosed(self, *ret):
		if ret is not None and len(ret):
			from Plugins.SystemPlugins.WirelessLan.Wlan import iStatus
			iStatus.stopWlanConsole()
			self.updateStatusbar()

	def WlanScanClosed(self, *ret):
		if ret[0] is not None:
			self.session.openWithCallback(self.AdapterSetupClosed, AdapterSetup, self.iface, ret[0])
		else:
			from Plugins.SystemPlugins.WirelessLan.Wlan import iStatus
			iStatus.stopWlanConsole()
			self.updateStatusbar()

	def restartLan(self, ret=False):
		if ret == True:
			iNetwork.restartNetwork(self.restartLanDataAvail)
			self.restartLanRef = self.session.openWithCallback(self.restartfinishedCB, MessageBox, _("Your network is restarting, Please wait..."), type=MessageBox.TYPE_INFO, enable_input=False)

	def restartLanDataAvail(self, data):
		if data == True:
			iNetwork.getInterfaces(self.getInterfacesDataAvail)

	def getInterfacesDataAvail(self, data):
		if data == True:
			self.restartLanRef.close(True)

	def restartfinishedCB(self, data):
		if data == True:
			self.updateStatusbar()
			self.session.open(MessageBox, _("Your network has finished restarting"), type=MessageBox.TYPE_INFO, timeout=10, default=False)

	def dataAvail(self, data):
		data = six.ensure_str(data)
		self.LinkState = None
		for line in data.splitlines():
			line = line.strip()
			if "Link detected:" in line:
				if "yes" in line:
					self.LinkState = True
				else:
					self.LinkState = False
		if self.LinkState:
			iNetwork.checkNetworkState(self.checkNetworkCB)
		else:
			self["statuspic"].setPixmapNum(1)
			self["statuspic"].show()

	def showErrorMessage(self):
		self.session.open(MessageBox, self.errortext, type=MessageBox.TYPE_INFO, timeout=10)

	def cleanup(self):
		iNetwork.stopLinkStateConsole()
		iNetwork.stopDeactivateInterfaceConsole()
		iNetwork.stopActivateInterfaceConsole()
		iNetwork.stopPingConsole()
		try:
			from Plugins.SystemPlugins.WirelessLan.Wlan import iStatus
		except ImportError:
			pass
		else:
			iStatus.stopWlanConsole()

	def getInfoCB(self, data, status):
		self.LinkState = None
		if data is not None:
			if data == True:
				if status is not None:
					if status[self.iface]["essid"] == "off" or status[self.iface]["accesspoint"] == "Not-Associated" or status[self.iface]["accesspoint"] == False:
						self.LinkState = False
						self["statuspic"].setPixmapNum(1)
						self["statuspic"].show()
					else:
						self.LinkState = True
						iNetwork.checkNetworkState(self.checkNetworkCB)

	def checkNetworkCB(self, data):
		if iNetwork.getAdapterAttribute(self.iface, "up") == True:
			if self.LinkState == True:
				if data <= 2:
					self["statuspic"].setPixmapNum(0)
				else:
					self["statuspic"].setPixmapNum(1)
				self["statuspic"].show()
			else:
				self["statuspic"].setPixmapNum(1)
				self["statuspic"].show()
		else:
			self["statuspic"].setPixmapNum(1)
			self["statuspic"].show()


class NetworkAdapterTest(Screen):
	def __init__(self, session, iface=None):
		Screen.__init__(self, session)
		self.setTitle(_("Network Test"))
		self.iface = iface
		self.oldInterfaceState = iNetwork.getAdapterAttribute(self.iface, "up")
		self.setLabels()
		self.onClose.append(self.cleanup)
		self.onHide.append(self.cleanup)

		self["updown_actions"] = NumberActionMap(["WizardActions", "ShortcutActions"],
		{
			"ok": self.KeyOK,
			"blue": self.KeyOK,
			"up": lambda: self.updownhandler("up"),
			"down": lambda: self.updownhandler("down"),

		}, -2)

		self["shortcuts"] = ActionMap(["ShortcutActions", "WizardActions"],
		{
			"red": self.cancel,
			"back": self.cancel,
		}, -2)
		self["infoshortcuts"] = ActionMap(["ShortcutActions", "WizardActions"],
		{
			"red": self.closeInfo,
			"back": self.closeInfo,
		}, -2)
		self["shortcutsgreen"] = ActionMap(["ShortcutActions"],
		{
			"green": self.KeyGreen,
		}, -2)
		self["shortcutsgreen_restart"] = ActionMap(["ShortcutActions"],
		{
			"green": self.KeyGreenRestart,
		}, -2)
		self["shortcutsyellow"] = ActionMap(["ShortcutActions"],
		{
			"yellow": self.KeyYellow,
		}, -2)

		self["shortcutsgreen_restart"].setEnabled(False)
		self["updown_actions"].setEnabled(False)
		self["infoshortcuts"].setEnabled(False)
		self.onClose.append(self.delTimer)
		self.onLayoutFinish.append(self.layoutFinished)
		self.steptimer = False
		self.nextstep = 0
		self.activebutton = 0
		self.nextStepTimer = eTimer()
		self.nextStepTimer.callback.append(self.nextStepTimerFire)

	def cancel(self):
		if self.oldInterfaceState == False:
			iNetwork.setAdapterAttribute(self.iface, "up", self.oldInterfaceState)
			iNetwork.deactivateInterface(self.iface)
		self.close()

	def closeInfo(self):
		self["shortcuts"].setEnabled(True)
		self["infoshortcuts"].setEnabled(False)
		self["InfoText"].hide()
		self["InfoTextBorder"].hide()
		self["key_red"].setText(_("Close"))

	def delTimer(self):
		del self.steptimer
		del self.nextStepTimer

	def nextStepTimerFire(self):
		self.nextStepTimer.stop()
		self.steptimer = False
		self.runTest()

	def updownhandler(self, direction):
		if direction == "up":
			if self.activebutton >= 2:
				self.activebutton -= 1
			else:
				self.activebutton = 6
			self.setActiveButton(self.activebutton)
		if direction == "down":
			if self.activebutton <= 5:
				self.activebutton += 1
			else:
				self.activebutton = 1
			self.setActiveButton(self.activebutton)

	def setActiveButton(self, button):
		if button == 1:
			self["EditSettingsButton"].setPixmapNum(0)
			self["EditSettings_Text"].setForegroundColorNum(0)
			self["NetworkInfo"].setPixmapNum(0)
			self["NetworkInfo_Text"].setForegroundColorNum(1)
			self["AdapterInfo"].setPixmapNum(1) 		  # active
			self["AdapterInfo_Text"].setForegroundColorNum(2)  # active
		if button == 2:
			self["AdapterInfo_Text"].setForegroundColorNum(1)
			self["AdapterInfo"].setPixmapNum(0)
			self["DhcpInfo"].setPixmapNum(0)
			self["DhcpInfo_Text"].setForegroundColorNum(1)
			self["NetworkInfo"].setPixmapNum(1) 		  # active
			self["NetworkInfo_Text"].setForegroundColorNum(2)  # active
		if button == 3:
			self["NetworkInfo"].setPixmapNum(0)
			self["NetworkInfo_Text"].setForegroundColorNum(1)
			self["IPInfo"].setPixmapNum(0)
			self["IPInfo_Text"].setForegroundColorNum(1)
			self["DhcpInfo"].setPixmapNum(1) 		  # active
			self["DhcpInfo_Text"].setForegroundColorNum(2) 	  # active
		if button == 4:
			self["DhcpInfo"].setPixmapNum(0)
			self["DhcpInfo_Text"].setForegroundColorNum(1)
			self["DNSInfo"].setPixmapNum(0)
			self["DNSInfo_Text"].setForegroundColorNum(1)
			self["IPInfo"].setPixmapNum(1)			# active
			self["IPInfo_Text"].setForegroundColorNum(2)  # active
		if button == 5:
			self["IPInfo"].setPixmapNum(0)
			self["IPInfo_Text"].setForegroundColorNum(1)
			self["EditSettingsButton"].setPixmapNum(0)
			self["EditSettings_Text"].setForegroundColorNum(0)
			self["DNSInfo"].setPixmapNum(1)			# active
			self["DNSInfo_Text"].setForegroundColorNum(2)  # active
		if button == 6:
			self["DNSInfo"].setPixmapNum(0)
			self["DNSInfo_Text"].setForegroundColorNum(1)
			self["EditSettingsButton"].setPixmapNum(1) 	   # active
			self["EditSettings_Text"].setForegroundColorNum(2)  # active
			self["AdapterInfo"].setPixmapNum(0)
			self["AdapterInfo_Text"].setForegroundColorNum(1)

	def runTest(self):
		next = self.nextstep
		if next == 0:
			self.doStep1()
		elif next == 1:
			self.doStep2()
		elif next == 2:
			self.doStep3()
		elif next == 3:
			self.doStep4()
		elif next == 4:
			self.doStep5()
		elif next == 5:
			self.doStep6()
		self.nextstep += 1

	def doStep1(self):
		self.steptimer = True
		self.nextStepTimer.start(300)
		self["key_yellow"].setText(_("Stop test"))

	def doStep2(self):
		self["Adapter"].setText(iNetwork.getFriendlyAdapterName(self.iface))
		self["Adapter"].setForegroundColorNum(2)
		self["Adaptertext"].setForegroundColorNum(1)
		self["AdapterInfo_Text"].setForegroundColorNum(1)
		self["AdapterInfo_OK"].show()
		self.steptimer = True
		self.nextStepTimer.start(300)

	def doStep3(self):
		self["Networktext"].setForegroundColorNum(1)
		self["Network"].setText(_("Please wait..."))
		self.getLinkState(self.iface)
		self["NetworkInfo_Text"].setForegroundColorNum(1)
		self.steptimer = True
		self.nextStepTimer.start(1000)

	def doStep4(self):
		self["Dhcptext"].setForegroundColorNum(1)
		if iNetwork.getAdapterAttribute(self.iface, "dhcp") == True:
			self["Dhcp"].setForegroundColorNum(2)
			self["Dhcp"].setText(_("enabled"))
			self["DhcpInfo_Check"].setPixmapNum(0)
		else:
			self["Dhcp"].setForegroundColorNum(1)
			self["Dhcp"].setText(_("disabled"))
			self["DhcpInfo_Check"].setPixmapNum(1)
		self["DhcpInfo_Check"].show()
		self["DhcpInfo_Text"].setForegroundColorNum(1)
		self.steptimer = True
		self.nextStepTimer.start(1000)

	def doStep5(self):
		self["IPtext"].setForegroundColorNum(1)
		self["IP"].setText(_("Please wait..."))
		iNetwork.checkNetworkState(self.NetworkStatedataAvail)

	def doStep6(self):
		self.steptimer = False
		self.nextStepTimer.stop()
		self["DNStext"].setForegroundColorNum(1)
		self["DNS"].setText(_("Please wait..."))
		iNetwork.checkDNSLookup(self.DNSLookupdataAvail)

	def KeyGreen(self):
		self["shortcutsgreen"].setEnabled(False)
		self["shortcutsyellow"].setEnabled(True)
		self["updown_actions"].setEnabled(False)
		self["key_yellow"].setText("")
		self["key_green"].setText("")
		self.steptimer = True
		self.nextStepTimer.start(1000)

	def KeyGreenRestart(self):
		self.nextstep = 0
		self.layoutFinished()
		self["Adapter"].setText("")
		self["Network"].setText("")
		self["Dhcp"].setText("")
		self["IP"].setText("")
		self["DNS"].setText("")
		self["AdapterInfo_Text"].setForegroundColorNum(0)
		self["NetworkInfo_Text"].setForegroundColorNum(0)
		self["DhcpInfo_Text"].setForegroundColorNum(0)
		self["IPInfo_Text"].setForegroundColorNum(0)
		self["DNSInfo_Text"].setForegroundColorNum(0)
		self["shortcutsgreen_restart"].setEnabled(False)
		self["shortcutsgreen"].setEnabled(False)
		self["shortcutsyellow"].setEnabled(True)
		self["updown_actions"].setEnabled(False)
		self["key_yellow"].setText("")
		self["key_green"].setText("")
		self.steptimer = True
		self.nextStepTimer.start(1000)

	def KeyOK(self):
		self["infoshortcuts"].setEnabled(True)
		self["shortcuts"].setEnabled(False)
		if self.activebutton == 1:  # Adapter Check
			self["InfoText"].setText(_("LAN adapter\n\nThis test detects your configured LAN adapter."))
			self["InfoTextBorder"].show()
			self["InfoText"].show()
			self["key_red"].setText(_("Back"))
		if self.activebutton == 2:  # LAN Check
			self["InfoText"].setText(_("Local network\n\nThis test checks whether a network cable is connected to your LAN adapter.\n\nIf you get a \"disconnected\" message:\n- Verify that a network cable is attached.\n- Verify that the cable is not broken."))
			self["InfoTextBorder"].show()
			self["InfoText"].show()
			self["key_red"].setText(_("Back"))
		if self.activebutton == 3:  # DHCP Check
			self["InfoText"].setText(_("DHCP\n\nThis test checks whether your LAN adapter is set up for automatic IP address configuration with DHCP.\n\nIf you get a \"disabled\" message:\n- Your LAN adapter is configured for manual IP setup.\n- Verify that you have entered correct IP informations in the adapter setup dialog.\n\nIf you get an \"enabled\" message:\n- Verify that you have a configured and working DHCP server in your network."))
			self["InfoTextBorder"].show()
			self["InfoText"].show()
			self["key_red"].setText(_("Back"))
		if self.activebutton == 4:  # IP Check
			self["InfoText"].setText(_("IP address\n\nThis test checks whether a valid IP address is found for your LAN adapter.\n\nIf you get a \"unconfirmed\" message:\n- No valid IP address was found.\n- Please check your DHCP server, cabling and adapter setup."))
			self["InfoTextBorder"].show()
			self["InfoText"].show()
			self["key_red"].setText(_("Back"))
		if self.activebutton == 5:  # DNS Check
			self["InfoText"].setText(_("Nameserver\n\nThis test checks for configured nameservers.\n\nIf you get a \"unconfirmed\" message:\n- Please check your DHCP server, cabling and adapter setup.\n- If you configured your nameservers manually please verify your entries in the \"Nameserver\" configuration."))
			self["InfoTextBorder"].show()
			self["InfoText"].show()
			self["key_red"].setText(_("Back"))
		if self.activebutton == 6:  # Edit Settings
			self.session.open(AdapterSetup, self.iface)

	def KeyYellow(self):
		self.nextstep = 0
		self["shortcutsgreen_restart"].setEnabled(True)
		self["shortcutsgreen"].setEnabled(False)
		self["shortcutsyellow"].setEnabled(False)
		self["key_green"].setText(_("Restart test"))
		self["key_yellow"].setText("")
		self.steptimer = False
		self.nextStepTimer.stop()

	def layoutFinished(self):
		self.setTitle("%s %s" % (_("Network Test:"), iNetwork.getFriendlyAdapterName(self.iface)))
		self["shortcutsyellow"].setEnabled(False)
		self["AdapterInfo_OK"].hide()
		self["NetworkInfo_Check"].hide()
		self["DhcpInfo_Check"].hide()
		self["IPInfo_Check"].hide()
		self["DNSInfo_Check"].hide()
		self["EditSettings_Text"].hide()
		self["EditSettingsButton"].hide()
		self["InfoText"].hide()
		self["InfoTextBorder"].hide()
		self["key_yellow"].setText("")

	def setLabels(self):
		self["Adaptertext"] = MultiColorLabel(_("LAN adapter"))
		self["Adapter"] = MultiColorLabel()
		self["AdapterInfo"] = MultiPixmap()
		self["AdapterInfo_Text"] = MultiColorLabel(_("Show info"))
		self["AdapterInfo_OK"] = Pixmap()

		if self.iface in iNetwork.wlan_interfaces:
			self["Networktext"] = MultiColorLabel(_("Wireless network"))
		else:
			self["Networktext"] = MultiColorLabel(_("Local network"))

		self["Network"] = MultiColorLabel()
		self["NetworkInfo"] = MultiPixmap()
		self["NetworkInfo_Text"] = MultiColorLabel(_("Show info"))
		self["NetworkInfo_Check"] = MultiPixmap()

		self["Dhcptext"] = MultiColorLabel(_("DHCP"))
		self["Dhcp"] = MultiColorLabel()
		self["DhcpInfo"] = MultiPixmap()
		self["DhcpInfo_Text"] = MultiColorLabel(_("Show info"))
		self["DhcpInfo_Check"] = MultiPixmap()

		self["IPtext"] = MultiColorLabel(_("IP address"))
		self["IP"] = MultiColorLabel()
		self["IPInfo"] = MultiPixmap()
		self["IPInfo_Text"] = MultiColorLabel(_("Show info"))
		self["IPInfo_Check"] = MultiPixmap()

		self["DNStext"] = MultiColorLabel(_("Nameserver"))
		self["DNS"] = MultiColorLabel()
		self["DNSInfo"] = MultiPixmap()
		self["DNSInfo_Text"] = MultiColorLabel(_("Show info"))
		self["DNSInfo_Check"] = MultiPixmap()

		self["EditSettings_Text"] = MultiColorLabel(_("Edit settings"))
		self["EditSettingsButton"] = MultiPixmap()

		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Start test"))
		self["key_yellow"] = StaticText(_("Stop test"))

		self["InfoTextBorder"] = Pixmap()
		self["InfoText"] = Label()

	def getLinkState(self, iface):
		if iface in iNetwork.wlan_interfaces:
			try:
				from Plugins.SystemPlugins.WirelessLan.Wlan import iStatus
			except:
				self["Network"].setForegroundColorNum(1)
				self["Network"].setText(_("disconnected"))
				self["NetworkInfo_Check"].setPixmapNum(1)
				self["NetworkInfo_Check"].show()
			else:
				iStatus.getDataForInterface(self.iface, self.getInfoCB)
		else:
			iNetwork.getLinkState(iface, self.LinkStatedataAvail)

	def LinkStatedataAvail(self, data):
		for item in data.splitlines():
			if "Link detected:" in item:
				if "yes" in item:
					self["Network"].setForegroundColorNum(2)
					self["Network"].setText(_("connected"))
					self["NetworkInfo_Check"].setPixmapNum(0)
				else:
					self["Network"].setForegroundColorNum(1)
					self["Network"].setText(_("disconnected"))
					self["NetworkInfo_Check"].setPixmapNum(1)
				break
		else:
			self["Network"].setText(_("unknown"))
		self["NetworkInfo_Check"].show()

	def NetworkStatedataAvail(self, data):
		if data <= 2:
			self["IP"].setForegroundColorNum(2)
			self["IP"].setText(_("confirmed"))
			self["IPInfo_Check"].setPixmapNum(0)
		else:
			self["IP"].setForegroundColorNum(1)
			self["IP"].setText(_("unconfirmed"))
			self["IPInfo_Check"].setPixmapNum(1)
		self["IPInfo_Check"].show()
		self["IPInfo_Text"].setForegroundColorNum(1)
		self.steptimer = True
		self.nextStepTimer.start(300)

	def DNSLookupdataAvail(self, data):
		if data <= 2:
			self["DNS"].setForegroundColorNum(2)
			self["DNS"].setText(_("confirmed"))
			self["DNSInfo_Check"].setPixmapNum(0)
		else:
			self["DNS"].setForegroundColorNum(1)
			self["DNS"].setText(_("unconfirmed"))
			self["DNSInfo_Check"].setPixmapNum(1)
		self["DNSInfo_Check"].show()
		self["DNSInfo_Text"].setForegroundColorNum(1)
		self["EditSettings_Text"].show()
		self["EditSettingsButton"].setPixmapNum(1)
		self["EditSettings_Text"].setForegroundColorNum(2)  # active
		self["EditSettingsButton"].show()
		self["key_yellow"].setText("")
		self["key_green"].setText(_("Restart test"))
		self["shortcutsgreen"].setEnabled(False)
		self["shortcutsgreen_restart"].setEnabled(True)
		self["shortcutsyellow"].setEnabled(False)
		self["updown_actions"].setEnabled(True)
		self.activebutton = 6

	def getInfoCB(self, data, status):
		if data is not None:
			if data == True:
				if status is not None:
					if status[self.iface]["essid"] == "off" or status[self.iface]["accesspoint"] == "Not-Associated" or status[self.iface]["accesspoint"] == False:
						self["Network"].setForegroundColorNum(1)
						self["Network"].setText(_("disconnected"))
						self["NetworkInfo_Check"].setPixmapNum(1)
						self["NetworkInfo_Check"].show()
					else:
						self["Network"].setForegroundColorNum(2)
						self["Network"].setText(_("connected"))
						self["NetworkInfo_Check"].setPixmapNum(0)
						self["NetworkInfo_Check"].show()

	def cleanup(self):
		iNetwork.stopLinkStateConsole()
		iNetwork.stopDNSConsole()
		try:
			from Plugins.SystemPlugins.WirelessLan.Wlan import iStatus
		except ImportError:
			pass
		else:
			iStatus.stopWlanConsole()


class NetworkMountsMenu(Screen, HelpableScreen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.setTitle(_("Mounts"))
		self.session = session
		self.onChangedEntry = []
		self.mainmenu = self.genMainMenu()
		self["menulist"] = MenuList(self.mainmenu)
		self["key_red"] = StaticText(_("Close"))
		self["introduction"] = StaticText()

		self["WizardActions"] = HelpableActionMap(self, "WizardActions",
			{
			"up": (self.up, _("Move up to previous entry")),
			"down": (self.down, _("Move down to next entry")),
			"left": (self.left, _("Move up to first entry")),
			"right": (self.right, _("Move down to last entry")),
			})

		self["OkCancelActions"] = HelpableActionMap(self, "OkCancelActions",
			{
			"cancel": (self.close, _("Exit mounts setup menu")),
			"ok": (self.ok, _("Select menu entry")),
			})

		self["ColorActions"] = HelpableActionMap(self, "ColorActions",
			{
			"red": (self.close, _("Exit networkadapter setup menu")),
			})

		self["actions"] = NumberActionMap(["WizardActions", "ShortcutActions"],
		{
			"ok": self.ok,
			"back": self.close,
			"up": self.up,
			"down": self.down,
			"red": self.close,
			"left": self.left,
			"right": self.right,
		}, -2)

		if not self.selectionChanged in self["menulist"].onSelectionChanged:
			self["menulist"].onSelectionChanged.append(self.selectionChanged)
		self.selectionChanged()

	def createSummary(self):
		from Screens.PluginBrowser import PluginBrowserSummary
		return PluginBrowserSummary

	def selectionChanged(self):
		item = self["menulist"].getCurrent()
		if item:
			if item[1][0] == "extendedSetup":
				self["introduction"].setText(_(item[1][1]))
			name = str(self["menulist"].getCurrent()[0])
			desc = self["introduction"].text
		else:
			name = ""
			desc = ""
		for cb in self.onChangedEntry:
			cb(name, desc)

	def ok(self):
		if self["menulist"].getCurrent()[1][0] == "extendedSetup":
			self.extended = self["menulist"].getCurrent()[1][2]
			self.extended(self.session)

	def up(self):
		self["menulist"].up()

	def down(self):
		self["menulist"].down()

	def left(self):
		self["menulist"].pageUp()

	def right(self):
		self["menulist"].pageDown()

	def genMainMenu(self):
		menu = []
		self.extended = None
		self.extendedSetup = None
		for p in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKMOUNTS):
			callFnc = p.fnc["ifaceSupported"](self)
			if callFnc is not None:
				self.extended = callFnc
				if "menuEntryName" in p.fnc:
					menuEntryName = p.fnc["menuEntryName"](self)
				else:
					menuEntryName = _("Extended Setup...")
				if "menuEntryDescription" in p.fnc:
					menuEntryDescription = p.fnc["menuEntryDescription"](self)
				else:
					menuEntryDescription = _("Extended Networksetup Plugin...")
				self.extendedSetup = ("extendedSetup", menuEntryDescription, self.extended)
				menu.append((menuEntryName, self.extendedSetup))
		return menu


class NetworkAfp(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("AFP"))
		self.skinName = "NetworkServiceSetup"
		self.onChangedEntry = []
		self["lab1"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Disabled")))
		self["lab2"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["key_red"] = Label(_("Remove Service"))
		self["key_green"] = Label(_("Start"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label()
		self["status_summary"] = StaticText()
		self["autostartstatus_summary"] = StaticText()
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.my_afp_active = False
		self.my_afp_run = False
		self["actions"] = ActionMap(["WizardActions", "ColorActions"],
		{
			"ok": self.close,
			"back": self.close,
			"red": self.UninstallCheck,
			"green": self.AfpStartStop,
			"yellow": self.activateAfp
		})
		self.service_name = "packagegroup-base-appletalk netatalk"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = True

	def AfpStartStop(self):
		if not self.my_afp_run:
			self.ConsoleB.ePopen("/etc/init.d/atalk start", self.StartStopCallback)
		elif self.my_afp_run:
			self.ConsoleB.ePopen("/etc/init.d/atalk stop", self.StartStopCallback)

	def activateAfp(self):
		if ServiceIsEnabled("atalk"):
			self.ConsoleB.ePopen("update-rc.d -f atalk remove", self.StartStopCallback)
		else:
			self.ConsoleB.ePopen("update-rc.d -f atalk defaults", self.StartStopCallback)

	def updateService(self, result=None, retval=None, extra_args=None):
		import process
		p = process.ProcessList()
		afp_process = str(p.named("afpd")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].setText(_("Disabled"))
		self.my_afp_active = False
		self.my_afp_run = False
		if ServiceIsEnabled("atalk"):
			self["labactive"].setText(_("Enabled"))
			self["labactive"].show()
			self.my_afp_active = True
		if afp_process:
			self.my_afp_run = True
		if self.my_afp_run:
			self["labstop"].hide()
			self["labactive"].show()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["lab2"].text + " " + self["labrun"].text
		else:
			self["labrun"].hide()
			self["labstop"].show()
			self["labactive"].show()
			self["key_green"].setText(_("Start"))
			status_summary = self["lab2"].text + " " + self["labstop"].text
		title = _("AFP Setup")
		autostartstatus_summary = self["lab1"].text + " " + self["labactive"].text

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)


class NetworkFtp(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("FTP"))
		self.skinName = "NetworkServiceSetup"
		self.onChangedEntry = []
		self["lab1"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Disabled")))
		self["lab2"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["key_green"] = Label(_("Start"))
		self["key_red"] = Label()
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label()
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.my_ftp_active = False
		self.my_ftp_run = False
		self["actions"] = ActionMap(["WizardActions", "ColorActions"],
		{
			"ok": self.close,
			"back": self.close,
			"green": self.FtpStartStop,
			"yellow": self.activateFtp
		})
		self.onLayoutFinish.append(self.updateService)
		self.reboot_at_end = False

	def FtpStartStop(self):
		commands = []
		if not self.my_ftp_run:
			commands.append("/etc/init.d/vsftpd start")
		elif self.my_ftp_run:
			commands.append("/etc/init.d/vsftpd stop")
		self.ConsoleB.eBatch(commands, self.StartStopCallback, debug=True)

	def activateFtp(self):
		commands = []
		if ServiceIsEnabled("vsftpd"):
			commands.append("update-rc.d -f vsftpd remove")
		else:
			commands.append("update-rc.d -f vsftpd defaults")
		self.ConsoleB.eBatch(commands, self.StartStopCallback, debug=True)

	def updateService(self):
		import process
		p = process.ProcessList()
		ftp_process = str(p.named("vsftpd")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].setText(_("Disabled"))
		self.my_ftp_active = False
		if ServiceIsEnabled("vsftpd"):
			self["labactive"].setText(_("Enabled"))
			self["labactive"].show()
			self.my_ftp_active = True

		self.my_ftp_run = False
		if ftp_process:
			self.my_ftp_run = True
		if self.my_ftp_run:
			self["labstop"].hide()
			self["labactive"].show()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["lab2"].text + " " + self["labrun"].text
		else:
			self["labrun"].hide()
			self["labstop"].show()
			self["labactive"].show()
			self["key_green"].setText(_("Start"))
			status_summary = self["lab2"].text + " " + self["labstop"].text
		title = _("FTP Setup")
		autostartstatus_summary = self["lab1"].text + " " + self["labactive"].text

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)


class NetworkNfs(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("NFS"))
		self.skinName = "NetworkServiceSetup"
		self.onChangedEntry = []
		self["lab1"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Disabled")))
		self["lab2"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["key_green"] = Label(_("Start"))
		self["key_red"] = Label(_("Remove Service"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label()
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.my_nfs_active = False
		self.my_nfs_run = False
		self["actions"] = ActionMap(["WizardActions", "ColorActions"],
		{
			"ok": self.close,
			"back": self.close,
			"red": self.UninstallCheck,
			"green": self.NfsStartStop,
			"yellow": self.Nfsset
		})
		self.service_name = "packagegroup-base-nfs"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = True

	def NfsStartStop(self):
		if not self.my_nfs_run:
			self.ConsoleB.ePopen("/etc/init.d/nfsserver start", self.StartStopCallback)
		elif self.my_nfs_run:
			self.ConsoleB.ePopen("/etc/init.d/nfsserver stop", self.StartStopCallback)

	def Nfsset(self):
		if ServiceIsEnabled("nfsserver"):
			self.ConsoleB.ePopen("update-rc.d -f nfsserver remove", self.StartStopCallback)
		else:
			self.ConsoleB.ePopen("update-rc.d -f nfsserver defaults 13", self.StartStopCallback)

	def updateService(self):
		import process
		p = process.ProcessList()
		nfs_process = str(p.named("nfsd")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].setText(_("Disabled"))
		self.my_nfs_active = False
		self.my_nfs_run = False
		if ServiceIsEnabled("nfsserver"):
			self["labactive"].setText(_("Enabled"))
			self["labactive"].show()
			self.my_nfs_active = True
		if nfs_process:
			self.my_nfs_run = True
		if self.my_nfs_run:
			self["labstop"].hide()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["lab2"].text + " " + self["labrun"].text
		else:
			self["labstop"].show()
			self["labrun"].hide()
			self["key_green"].setText(_("Start"))
			status_summary = self["lab2"].text + " " + self["labstop"].text
		title = _("NFS Setup")
		autostartstatus_summary = self["lab1"].text + " " + self["labactive"].text

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)


class NetworkOpenvpn(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("OpenVPN"))
		self.skinName = "NetworkServiceSetup"
		self.onChangedEntry = []
		self["lab1"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Disabled")))
		self["lab2"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["key_green"] = Label(_("Start"))
		self["key_red"] = Label(_("Remove Service"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label(_("Show Log"))
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.my_vpn_active = False
		self.my_vpn_run = False
		self["actions"] = ActionMap(["WizardActions", "ColorActions"],
		{
			"ok": self.close,
			"back": self.close,
			"red": self.UninstallCheck,
			"green": self.VpnStartStop,
			"yellow": self.activateVpn,
			"blue": self.Vpnshowlog
		})
		self.service_name = "openvpn"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = False

	def Vpnshowlog(self):
		self.session.open(NetworkVpnLog)

	def VpnStartStop(self):
		if not self.my_vpn_run:
			self.ConsoleB.ePopen("/etc/init.d/openvpn start", self.StartStopCallback)
		elif self.my_vpn_run:
			self.ConsoleB.ePopen("/etc/init.d/openvpn stop", self.StartStopCallback)

	def activateVpn(self):
		if ServiceIsEnabled("openvpn"):
			self.ConsoleB.ePopen("update-rc.d -f openvpn remove", self.StartStopCallback)
		else:
			self.ConsoleB.ePopen("update-rc.d -f openvpn defaults", self.StartStopCallback)

	def updateService(self):
		import process
		p = process.ProcessList()
		openvpn_process = str(p.named("openvpn")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].setText(_("Disabled"))
		self.my_Vpn_active = False
		self.my_vpn_run = False
		if ServiceIsEnabled("openvpn"):
			self["labactive"].setText(_("Enabled"))
			self["labactive"].show()
			self.my_Vpn_active = True
		if openvpn_process:
			self.my_vpn_run = True
		if self.my_vpn_run:
			self["labstop"].hide()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["lab2"].text + " " + self["labrun"].text
		else:
			self["labstop"].show()
			self["labrun"].hide()
			self["key_green"].setText(_("Start"))
			status_summary = self["lab2"].text + " " + self["labstop"].text
		title = _("OpenVpn Setup")
		autostartstatus_summary = self["lab1"].text + " " + self["labactive"].text

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)


class NetworkVpnLog(LogBase):
	def __init__(self, session):
		LogBase.__init__(self, session, "/etc/openvpn/tmp.log")


class NetworkSamba(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Samba"))
		self.skinName = "NetworkServiceSetup"
		self.onChangedEntry = []
		self["lab1"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Disabled")))
		self["lab2"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["key_green"] = Label(_("Start"))
		self["key_red"] = Label(_("Remove Service"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label(_("Show Log"))
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.my_Samba_active = False
		self.my_Samba_run = False
		self["actions"] = ActionMap(["WizardActions", "ColorActions"],
		{
			"ok": self.close,
			"back": self.close,
			"red": self.UninstallCheck,
			"green": self.SambaStartStop,
			"yellow": self.activateSamba,
			"blue": self.Sambashowlog
		})
		self.service_name = "packagegroup-base-smbfs-server"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = True

	def Sambashowlog(self):
		self.session.open(NetworkSambaLog)

	def SambaStartStop(self):
		commands = []
		if not self.my_Samba_run:
			commands.append("/etc/init.d/samba start")
		elif self.my_Samba_run:
			commands.append("/etc/init.d/samba stop")
			commands.append("killall nmbd")
			commands.append("killall smbd")
		self.ConsoleB.eBatch(commands, self.StartStopCallback, debug=True)

	def activateSamba(self):
		commands = []
		if ServiceIsEnabled("samba"):
			commands.append("update-rc.d -f samba remove")
		else:
			commands.append("update-rc.d -f samba defaults")
		self.ConsoleB.eBatch(commands, self.StartStopCallback, debug=True)

	def updateService(self):
		import process
		p = process.ProcessList()
		samba_process = str(p.named("smbd")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].setText(_("Disabled"))
		self.my_Samba_active = False
		if ServiceIsEnabled("samba"):
			self["labactive"].setText(_("Enabled"))
			self["labactive"].show()
			self.my_Samba_active = True

		self.my_Samba_run = False
		if samba_process:
			self.my_Samba_run = True
		if self.my_Samba_run:
			self["labstop"].hide()
			self["labactive"].show()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["lab2"].text + " " + self["labrun"].text
		else:
			self["labrun"].hide()
			self["labstop"].show()
			self["labactive"].show()
			self["key_green"].setText(_("Start"))
			status_summary = self["lab2"].text + " " + self["labstop"].text
		title = _("Samba Setup")
		autostartstatus_summary = self["lab1"].text + " " + self["labactive"].text

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)


class NetworkSambaLog(LogBase):
	def __init__(self, session):
		LogBase.__init__(self, session, "/tmp/smb.log")


class NetworkTelnet(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Telnet"))
		self.skinName = "NetworkServiceSetup"
		self.onChangedEntry = []
		self["lab1"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Disabled")))
		self["lab2"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["key_green"] = Label(_("Start"))
		self["key_yellow"] = Label(_("Autostart"))
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.my_telnet_active = False
		self.my_telnet_run = False
		self["actions"] = ActionMap(["WizardActions", "ColorActions"],
		{
			"ok": self.close,
			"back": self.close,
			"green": self.TelnetStartStop,
			"yellow": self.activateTelnet
		})
		self.reboot_at_end = False

	def TelnetStartStop(self):
		commands = []
		if fileExists("/etc/init.d/telnetd.busybox"):
			if self.my_telnet_run:
				commands.append("/etc/init.d/telnetd.busybox stop")
			else:
				commands.append("/bin/su -l -c '/etc/init.d/telnetd.busybox start'")
			self.ConsoleB.eBatch(commands, self.StartStopCallback, debug=True)

	def activateTelnet(self):
		commands = []
		if fileExists("/etc/init.d/telnetd.busybox"):
			if ServiceIsEnabled("telnetd.busybox"):
				commands.append("update-rc.d -f telnetd.busybox remove")
			else:
				commands.append("update-rc.d -f telnetd.busybox defaults")
		self.ConsoleB.eBatch(commands, self.StartStopCallback, debug=True)

	def updateService(self):
		import process
		p = process.ProcessList()
		telnet_process = str(p.named("telnetd")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].setText(_("Disabled"))
		self.my_telnet_active = False
		self.my_telnet_run = False
		if ServiceIsEnabled("telnetd.busybox"):
			self["labactive"].setText(_("Enabled"))
			self["labactive"].show()
			self.my_telnet_active = True

		if telnet_process:
			self.my_telnet_run = True
		if self.my_telnet_run:
			self["labstop"].hide()
			self["labactive"].show()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["lab2"].text + " " + self["labrun"].text
		else:
			self["labrun"].hide()
			self["labstop"].show()
			self["labactive"].show()
			self["key_green"].setText(_("Start"))
			status_summary = self["lab2"].text + " " + self["labstop"].text
		title = _("Telnet Setup")
		autostartstatus_summary = self["lab1"].text + " " + self["labactive"].text

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)


class NetworkInadyn(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Inadyn"))
		self.onChangedEntry = []
		self["autostart"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Active")))
		self["labdisabled"] = Label(_(_("Disabled")))
		self["status"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["time"] = Label(_("Time Update in Minutes:"))
		self["labtime"] = Label()
		self["username"] = Label(_("Username") + ":")
		self["labuser"] = Label()
		self["password"] = Label(_("Password") + ":")
		self["labpass"] = Label()
		self["alias"] = Label(_("Alias") + ":")
		self["labalias"] = Label()
		self["sactive"] = Pixmap()
		self["sinactive"] = Pixmap()
		self["system"] = Label(_("System") + ":")
		self["labsys"] = Label()
		self["key_red"] = Label(_("Remove Service"))
		self["key_green"] = Label(_("Start"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label(_("Show Log"))
		self["key_menu"] = StaticText(_("MENU"))
		self["actions"] = ActionMap(["WizardActions", "ColorActions", "SetupActions"],
		{
			"ok": self.setupinadyn,
			"back": self.close,
			"menu": self.setupinadyn,
			"red": self.UninstallCheck,
			"green": self.InadynStartStop,
			"yellow": self.autostart,
			"blue": self.inaLog
		})
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.service_name = "inadyn-mt"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = False

	def InadynStartStop(self):
		if not self.my_inadyn_run:
			self.ConsoleB.ePopen("/etc/init.d/inadyn-mt start", self.StartStopCallback)
		elif self.my_inadyn_run:
			self.ConsoleB.ePopen("/etc/init.d/inadyn-mt stop", self.StartStopCallback)

	def autostart(self):
		if ServiceIsEnabled("inadyn-mt"):
			self.ConsoleB.ePopen("update-rc.d -f inadyn-mt remove", self.StartStopCallback)
		else:
			self.ConsoleB.ePopen("update-rc.d -f inadyn-mt defaults", self.StartStopCallback)

	def updateService(self):
		import process
		p = process.ProcessList()
		inadyn_process = str(p.named("inadyn-mt")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].hide()
		self["labdisabled"].hide()
		self["sactive"].hide()
		self.my_inadyn_active = False
		self.my_inadyn_run = False
		if ServiceIsEnabled("inadyn-mt"):
			self["labdisabled"].hide()
			self["labactive"].show()
			self.my_inadyn_active = True
			autostartstatus_summary = self["autostart"].text + " " + self["labactive"].text
		else:
			self["labactive"].hide()
			self["labdisabled"].show()
			autostartstatus_summary = self["autostart"].text + " " + self["labdisabled"].text
		if inadyn_process:
			self.my_inadyn_run = True
		if self.my_inadyn_run:
			self["labstop"].hide()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["status"].text + " " + self["labrun"].text
		else:
			self["labstop"].show()
			self["labrun"].hide()
			self["key_green"].setText(_("Start"))
			status_summary = self["status"].text + " " + self["labstop"].text

		#self.my_nabina_state = False
		if fileExists("/etc/inadyn.conf"):
			f = open("/etc/inadyn.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("username "):
					line = line[9:]
					self["labuser"].setText(line)
				elif line.startswith("password "):
					line = line[9:]
					self["labpass"].setText(line)
				elif line.startswith("alias "):
					line = line[6:]
					self["labalias"].setText(line)
				elif line.startswith("update_period_sec "):
					line = line[18:]
					line = (int(line) // 60)
					self["labtime"].setText(str(line))
				elif line.startswith("dyndns_system ") or line.startswith("#dyndns_system "):
					if line.startswith("#"):
						line = line[15:]
						self["sactive"].hide()
					else:
						line = line[14:]
						self["sactive"].show()
					self["labsys"].setText(line)
			f.close()
		title = _("Inadyn Setup")

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)

	def setupinadyn(self):
		self.session.openWithCallback(self.updateService, NetworkInadynSetup)

	def inaLog(self):
		self.session.open(NetworkInadynLog)


class NetworkInadynSetup(ConfigListScreen, HelpableScreen, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.setTitle(_("NetworkInadynSetup"))
		self.skinName = ["NetworkInadynSetup", "Setup"]
		ConfigListScreen.__init__(self, [], session=self.session, on_change=self.changedEntry, fullUI=True)
		self.updateList()

	def updateList(self):
		self.list = []
		# standard defaults just in case the config file does not exist
		self.ina_user = NoSave(ConfigText(fixed_size=False))
		self.ina_pass = NoSave(ConfigText(fixed_size=False))
		self.ina_alias = NoSave(ConfigText(fixed_size=False))
		self.ina_period = NoSave(ConfigNumber())
		self.ina_sysactive = NoSave(ConfigYesNo(default=False))
		self.ina_system = NoSave(ConfigSelection(default="dyndns@dyndns.org", choices=[("dyndns@dyndns.org", "dyndns@dyndns.org"), ("statdns@dyndns.org", "statdns@dyndns.org"), ("custom@dyndns.org", "custom@dyndns.org"), ("default@no-ip.com", "default@no-ip.com")]))

		if fileExists("/etc/inadyn.conf"):
			f = open("/etc/inadyn.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("username "):
					line = line[9:]
					self.ina_user = NoSave(ConfigText(fixed_size=False, default=line))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Username") + ":", self.ina_user))
				elif line.startswith("password "):
					line = line[9:]
					self.ina_pass = NoSave(ConfigText(fixed_size=False, default=line))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Password") + ":", self.ina_pass))
				elif line.startswith("alias "):
					line = line[6:]
					self.ina_alias = NoSave(ConfigText(fixed_size=False, default=line))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Alias") + ":", self.ina_alias))
				elif line.startswith("update_period_sec "):
					line = (int(line[18:]) // 60)
					self.ina_period = NoSave(ConfigNumber(default=line))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Time update in minutes") + ":", self.ina_period))
				elif line.startswith("dyndns_system ") or line.startswith("#dyndns_system "):
					if not line.startswith("#"):
						default = True
						line = line[14:]
					else:
						default = False
						line = line[15:]
					self.ina_sysactive = NoSave(ConfigYesNo(default=default))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Set system") + ":", self.ina_sysactive))
					# self.ina_value = line # looks like dead code
					ina_system1 = getConfigListEntry(_("System") + ":", self.ina_system)
					self.list.append(ina_system1)

			f.close()
		self["config"].list = self.list

	def keySave(self):  # saveIna
		if fileExists("/etc/inadyn.conf"):
			inme = open("/etc/inadyn.conf", "r")
			out = open("/etc/inadyn.conf.tmp", "w")
			for line in inme.readlines():
				line = line.replace("\n", "")
				if line.startswith("username "):
					line = ("username " + self.ina_user.value.strip())
				elif line.startswith("password "):
					line = ("password " + self.ina_pass.value.strip())
				elif line.startswith("alias "):
					line = ("alias " + self.ina_alias.value.strip())
				elif line.startswith("update_period_sec "):
					strview = (self.ina_period.value * 60)
					strview = str(strview)
					line = ("update_period_sec " + strview)
				elif line.startswith("dyndns_system ") or line.startswith("#dyndns_system "):
					if self.ina_sysactive.value:
						line = ("dyndns_system " + self.ina_system.value.strip())
					else:
						line = ("#dyndns_system " + self.ina_system.value.strip())
				out.write((line + "\n"))
			out.close()
			inme.close()
		else:
			self.session.open(MessageBox, _("Sorry your Inadyn config is missing"), MessageBox.TYPE_INFO)
			self.close()
		if fileExists("/etc/inadyn.conf.tmp"):
			rename("/etc/inadyn.conf.tmp", "/etc/inadyn.conf")
		self.close()


class NetworkInadynLog(LogBase):
	def __init__(self, session):
		LogBase.__init__(self, session, "/var/log/inadyn.log")


config.networkushare = ConfigSubsection()
config.networkushare.mediafolders = NoSave(ConfigLocations(default=""))


class NetworkuShare(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("uShare"))
		self.onChangedEntry = []
		self["autostart"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Active")))
		self["labdisabled"] = Label(_(_("Disabled")))
		self["status"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["username"] = Label(_("uShare Name") + ":")
		self["labuser"] = Label()
		self["iface"] = Label(_("Interface") + ":")
		self["labiface"] = Label()
		self["port"] = Label(_("uShare Port") + ":")
		self["labport"] = Label()
		self["telnetport"] = Label(_("Telnet Port") + ":")
		self["labtelnetport"] = Label()
		self["sharedir"] = Label(_("Share Folders") + ":")
		self["labsharedir"] = Label()
		self["web"] = Label(_("Web Interface") + ":")
		self["webactive"] = Pixmap()
		self["webinactive"] = Pixmap()
		self["telnet"] = Label(_("Telnet Interface") + ":")
		self["telnetactive"] = Pixmap()
		self["telnetinactive"] = Pixmap()
		self["xbox"] = Label(_("XBox 360 support") + ":")
		self["xboxactive"] = Pixmap()
		self["xboxinactive"] = Pixmap()
		self["dlna"] = Label(_("DLNA support") + ":")
		self["dlnaactive"] = Pixmap()
		self["dlnainactive"] = Pixmap()

		self["key_red"] = Label(_("Remove Service"))
		self["key_green"] = Label(_("Start"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label(_("Show Log"))
		self["key_menu"] = StaticText(_("MENU"))
		self["actions"] = ActionMap(["WizardActions", "ColorActions", "SetupActions"],
		{
			"ok": self.setupushare,
			"back": self.close,
			"menu": self.setupushare,
			"red": self.UninstallCheck,
			"green": self.uShareStartStop,
			"yellow": self.autostart,
			"blue": self.ushareLog
		})
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.service_name = "ushare"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = False

	def uShareStartStop(self):
		if not self.my_ushare_run:
			self.ConsoleB.ePopen("/etc/init.d/ushare start >> /tmp/uShare.log", self.StartStopCallback)
		elif self.my_ushare_run:
			self.ConsoleB.ePopen("/etc/init.d/ushare stop >> /tmp/uShare.log", self.StartStopCallback)

	def autostart(self):
		if ServiceIsEnabled("ushare"):
			self.ConsoleB.ePopen("update-rc.d -f ushare remove", self.StartStopCallback)
		else:
			self.ConsoleB.ePopen("update-rc.d -f ushare defaults", self.StartStopCallback)

	def updateService(self):
		import process
		p = process.ProcessList()
		ushare_process = str(p.named("ushare")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].hide()
		self["labdisabled"].hide()
		self.my_ushare_active = False
		self.my_ushare_run = False
		if not fileExists("/tmp/uShare.log"):
			f = open("/tmp/uShare.log", "w")
			f.write("")
			f.close()
		if ServiceIsEnabled("ushare"):
			self["labdisabled"].hide()
			self["labactive"].show()
			self.my_ushare_active = True
			autostartstatus_summary = self["autostart"].text + " " + self["labactive"].text
		else:
			self["labactive"].hide()
			self["labdisabled"].show()
			autostartstatus_summary = self["autostart"].text + " " + self["labdisabled"].text
		if ushare_process:
			self.my_ushare_run = True
		if self.my_ushare_run:
			self["labstop"].hide()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["status"].text + " " + self["labstop"].text
		else:
			self["labstop"].show()
			self["labrun"].hide()
			self["key_green"].setText(_("Start"))
			status_summary = self["status"].text + " " + self["labstop"].text

		if fileExists("/etc/ushare.conf"):
			f = open("/etc/ushare.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("USHARE_NAME="):
					line = line[12:]
					self["labuser"].setText(line)
				elif line.startswith("USHARE_IFACE="):
					line = line[13:]
					self["labiface"].setText(line)
				elif line.startswith("USHARE_PORT="):
					line = line[12:]
					self["labport"].setText(line)
				elif line.startswith("USHARE_TELNET_PORT="):
					line = line[19:]
					self["labtelnetport"].setText(line)
				elif line.startswith("USHARE_DIR="):
					line = line[11:]
					self.mediafolders = line
					self["labsharedir"].setText(line)
				elif line.startswith("ENABLE_WEB="):
					if line[11:] == "no":
						self["webactive"].hide()
						self["webinactive"].show()
					else:
						self["webactive"].show()
						self["webinactive"].hide()
				elif line.startswith("ENABLE_TELNET="):
					if line[14:] == "no":
						self["telnetactive"].hide()
						self["telnetinactive"].show()
					else:
						self["telnetactive"].show()
						self["telnetinactive"].hide()
				elif line.startswith("ENABLE_XBOX="):
					if line[12:] == "no":
						self["xboxactive"].hide()
						self["xboxinactive"].show()
					else:
						self["xboxactive"].show()
						self["xboxinactive"].hide()
				elif line.startswith("ENABLE_DLNA="):
					if line[12:] == "no":
						self["dlnaactive"].hide()
						self["dlnainactive"].show()
					else:
						self["dlnaactive"].show()
						self["dlnainactive"].hide()
			f.close()
		title = _("uShare Setup")

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)

	def setupushare(self):
		self.session.openWithCallback(self.updateService, NetworkuShareSetup)

	def ushareLog(self):
		self.session.open(NetworkuShareLog)


class NetworkuShareSetup(ConfigListScreen, HelpableScreen, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self.skinName = ["NetworkuShareSetup", "Setup"]
		ConfigListScreen.__init__(self, [], session=self.session, on_change=self.changedEntry, fullUI=True)
		self.setTitle(_("uShare Setup"))
		self["key_yellow"] = Label(_("Shares"))
		self["actions"] = ActionMap(["ColorActions"],
		{
			"yellow": self.selectfolders,
		})
		self.updateList()

	def updateList(self, ret=None):
		self.list = []
		self.ushare_user = NoSave(ConfigText(default=getBoxType(), fixed_size=False))
		self.ushare_iface = NoSave(ConfigText(fixed_size=False))
		self.ushare_port = NoSave(ConfigNumber())
		self.ushare_telnetport = NoSave(ConfigNumber())
		self.ushare_web = NoSave(ConfigYesNo(default=True))
		self.ushare_telnet = NoSave(ConfigYesNo(default=True))
		self.ushare_xbox = NoSave(ConfigYesNo(default=True))
		self.ushare_ps3 = NoSave(ConfigYesNo(default=True))
		# looks like dead code
		#self.ushare_system = NoSave(ConfigSelection(default = "dyndns@dyndns.org", choices = [("dyndns@dyndns.org", "dyndns@dyndns.org"), ("statdns@dyndns.org", "statdns@dyndns.org"), ("custom@dyndns.org", "custom@dyndns.org")]))

		if fileExists("/etc/ushare.conf"):
			f = open("/etc/ushare.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("USHARE_NAME="):
					line = line[12:]
					self.ushare_user = NoSave(ConfigText(default=line, fixed_size=False))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("uShare name") + ":", self.ushare_user))
				elif line.startswith("USHARE_IFACE="):
					line = line[13:]
					self.ushare_iface = NoSave(ConfigText(default=line, fixed_size=False))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Interface") + ":", self.ushare_iface))
				elif line.startswith("USHARE_PORT="):
					line = int(line[12:])
					self.ushare_port = NoSave(ConfigNumber(default=line))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("uShare port") + ":", self.ushare_port))
				elif line.startswith("USHARE_TELNET_PORT="):
					line = int(line[19:])
					self.ushare_telnetport = NoSave(ConfigNumber(default=line))  # overwrite so we start with the correct defaults
					self.list.append(getConfigListEntry(_("Telnet port") + ":", self.ushare_telnetport))
				elif line.startswith("ENABLE_WEB="):
					if line[11:] == "no":
						default = False
					else:
						default = True
					self.ushare_web = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("Web interface") + ":", self.ushare_web))
				elif line.startswith("ENABLE_TELNET="):
					if line[14:] == "no":
						default = False
					else:
						default = True
					self.ushare_telnet = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("Telnet interface") + ":", self.ushare_telnet))
				elif line.startswith("ENABLE_XBOX="):
					if line[12:] == "no":
						default = False
					else:
						default = True
					self.ushare_xbox = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("XBox 360 support") + ":", self.ushare_xbox))
				elif line.startswith("ENABLE_DLNA="):
					if line[12:] == "no":
						default = False
					else:
						default = True
					self.ushare_ps3 = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("DLNA support") + ":", self.ushare_ps3))
			f.close()
		self["config"].list = self.list

	def keySave(self):
		if fileExists("/etc/ushare.conf"):
			inme = open("/etc/ushare.conf", "r")
			out = open("/etc/ushare.conf.tmp", "w")
			for line in inme.readlines():
				line = line.replace("\n", "")
				if line.startswith("USHARE_NAME="):
					line = ("USHARE_NAME=" + self.ushare_user.value.strip())
				elif line.startswith("USHARE_IFACE="):
					line = ("USHARE_IFACE=" + self.ushare_iface.value.strip())
				elif line.startswith("USHARE_PORT="):
					line = ("USHARE_PORT=" + str(self.ushare_port.value))
				elif line.startswith("USHARE_TELNET_PORT="):
					line = ("USHARE_TELNET_PORT=" + str(self.ushare_telnetport.value))
				elif line.startswith("USHARE_DIR="):
					line = ("USHARE_DIR=" + ", ".join(config.networkushare.mediafolders.value))
				elif line.startswith("ENABLE_WEB="):
					if not self.ushare_web.value:
						line = "ENABLE_WEB=no"
					else:
						line = "ENABLE_WEB=yes"
				elif line.startswith("ENABLE_TELNET="):
					if not self.ushare_telnet.value:
						line = "ENABLE_TELNET=no"
					else:
						line = "ENABLE_TELNET=yes"
				elif line.startswith("ENABLE_XBOX="):
					if not self.ushare_xbox.value:
						line = "ENABLE_XBOX=no"
					else:
						line = "ENABLE_XBOX=yes"
				elif line.startswith("ENABLE_DLNA="):
					if not self.ushare_ps3.value:
						line = "ENABLE_DLNA=no"
					else:
						line = "ENABLE_DLNA=yes"
				out.write((line + "\n"))
			out.close()
			inme.close()
		else:
			open("/tmp/uShare.log", "a").write(_("Sorry your uShare config is missing") + "\n")
			self.session.open(MessageBox, _("Sorry your uShare config is missing"), MessageBox.TYPE_INFO)
			self.close()
		if fileExists("/etc/ushare.conf.tmp"):
			rename("/etc/ushare.conf.tmp", "/etc/ushare.conf")
		self.close()

	def selectfolders(self):
		self.session.openWithCallback(self.updateList, uShareSelection)


class uShareSelection(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Select Folders"))
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText()

		if fileExists("/etc/ushare.conf"):
			f = open("/etc/ushare.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("USHARE_DIR="):
					line = line[11:]
					self.mediafolders = line
		self.selectedFiles = [str(n) for n in self.mediafolders.split(", ")]
		defaultDir = "/media/"
		self.filelist = MultiFileSelectList(self.selectedFiles, defaultDir, showFiles=False)
		self["checkList"] = self.filelist

		self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ShortcutActions"],
		{
			"cancel": self.exit,
			"red": self.exit,
			"yellow": self.changeSelectionState,
			"green": self.saveSelection,
			"ok": self.okClicked,
			"left": self.left,
			"right": self.right,
			"down": self.down,
			"up": self.up
		}, -1)
		if not self.selectionChanged in self["checkList"].onSelectionChanged:
			self["checkList"].onSelectionChanged.append(self.selectionChanged)
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		idx = 0
		self["checkList"].moveToIndex(idx)
		self.selectionChanged()

	def selectionChanged(self):
		current = self["checkList"].getCurrent()[0]
		if current[2] == True:
			self["key_yellow"].setText(_("Deselect"))
		else:
			self["key_yellow"].setText(_("Select"))

	def up(self):
		self["checkList"].up()

	def down(self):
		self["checkList"].down()

	def left(self):
		self["checkList"].pageUp()

	def right(self):
		self["checkList"].pageDown()

	def changeSelectionState(self):
		self["checkList"].changeSelectionState()
		self.selectedFiles = self["checkList"].getSelectedList()

	def saveSelection(self):
		self.selectedFiles = self["checkList"].getSelectedList()
		config.networkushare.mediafolders.value = self.selectedFiles
		self.close(None)

	def exit(self):
		self.close(None)

	def okClicked(self):
		if self.filelist.canDescent():
			self.filelist.descent()


class NetworkuShareLog(LogBase):
	def __init__(self, session):
		LogBase.__init__(self, session, "/tmp/uShare.log")


config.networkminidlna = ConfigSubsection()
config.networkminidlna.mediafolders = NoSave(ConfigLocations(default=""))


class NetworkMiniDLNA(NSCommon, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("MiniDLNA"))
		self.onChangedEntry = []
		self["autostart"] = Label(_("Autostart:"))
		self["labactive"] = Label(_(_("Active")))
		self["labdisabled"] = Label(_(_("Disabled")))
		self["status"] = Label(_("Current Status:"))
		self["labstop"] = Label(_("Stopped"))
		self["labrun"] = Label(_("Running"))
		self["username"] = Label(_("Name") + ":")
		self["labuser"] = Label()
		self["iface"] = Label(_("Interface") + ":")
		self["labiface"] = Label()
		self["port"] = Label(_("Port") + ":")
		self["labport"] = Label()
		self["serialno"] = Label(_("Serial No") + ":")
		self["labserialno"] = Label()
		self["sharedir"] = Label(_("Share Folders") + ":")
		self["labsharedir"] = Label()
		self["inotify"] = Label(_("Inotify Monitoring") + ":")
		self["inotifyactive"] = Pixmap()
		self["inotifyinactive"] = Pixmap()
		self["tivo"] = Label(_("TiVo support") + ":")
		self["tivoactive"] = Pixmap()
		self["tivoinactive"] = Pixmap()
		self["dlna"] = Label(_("Strict DLNA") + ":")
		self["dlnaactive"] = Pixmap()
		self["dlnainactive"] = Pixmap()

		self["key_red"] = Label(_("Remove Service"))
		self["key_green"] = Label(_("Start"))
		self["key_yellow"] = Label(_("Autostart"))
		self["key_blue"] = Label(_("Show Log"))
		self["key_menu"] = StaticText(_("MENU"))
		self["actions"] = ActionMap(["WizardActions", "ColorActions", "SetupActions"],
		{
			"ok": self.setupminidlna,
			"back": self.close,
			"menu": self.setupminidlna,
			"red": self.UninstallCheck,
			"green": self.MiniDLNAStartStop,
			"yellow": self.autostart,
			"blue": self.minidlnaLog
		})
		self.Console = Console()
		self.ConsoleB = Console(binary=True)
		self.service_name = "minidlna"
		self.onLayoutFinish.append(self.InstallCheck)
		self.reboot_at_end = False

	def MiniDLNAStartStop(self):
		if not self.my_minidlna_run:
			self.ConsoleB.ePopen("/etc/init.d/minidlna start", self.StartStopCallback)
		elif self.my_minidlna_run:
			self.ConsoleB.ePopen("/etc/init.d/minidlna stop", self.StartStopCallback)

	def autostart(self):
		if ServiceIsEnabled("minidlna"):
			self.ConsoleB.ePopen("update-rc.d -f minidlna remove", self.StartStopCallback)
		else:
			self.ConsoleB.ePopen("update-rc.d -f minidlna defaults", self.StartStopCallback)

	def updateService(self):
		import process
		p = process.ProcessList()
		minidlna_process = str(p.named("minidlnad")).strip("[]")
		self["labrun"].hide()
		self["labstop"].hide()
		self["labactive"].hide()
		self["labdisabled"].hide()
		self.my_minidlna_active = False
		self.my_minidlna_run = False
		if ServiceIsEnabled("minidlna"):
			self["labdisabled"].hide()
			self["labactive"].show()
			self.my_minidlna_active = True
			autostartstatus_summary = self["autostart"].text + " " + self["labactive"].text
		else:
			self["labactive"].hide()
			self["labdisabled"].show()
			autostartstatus_summary = self["autostart"].text + " " + self["labdisabled"].text
		if minidlna_process:
			self.my_minidlna_run = True
		if self.my_minidlna_run:
			self["labstop"].hide()
			self["labrun"].show()
			self["key_green"].setText(_("Stop"))
			status_summary = self["status"].text + " " + self["labstop"].text
		else:
			self["labstop"].show()
			self["labrun"].hide()
			self["key_green"].setText(_("Start"))
			status_summary = self["status"].text + " " + self["labstop"].text

		if fileExists("/etc/minidlna.conf"):
			f = open("/etc/minidlna.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("friendly_name="):
					line = line[14:]
					self["labuser"].setText(line)
				elif line.startswith("network_interface="):
					line = line[18:]
					self["labiface"].setText(line)
				elif line.startswith("port="):
					line = line[5:]
					self["labport"].setText(line)
				elif line.startswith("serial="):
					line = line[7:]
					self["labserialno"].setText(line)
				elif line.startswith("media_dir="):
					line = line[10:]
					self.mediafolders = line
					self["labsharedir"].setText(line)
				elif line.startswith("inotify="):
					if line[8:] == "no":
						self["inotifyactive"].hide()
						self["inotifyinactive"].show()
					else:
						self["inotifyactive"].show()
						self["inotifyinactive"].hide()
				elif line.startswith("enable_tivo="):
					if line[12:] == "no":
						self["tivoactive"].hide()
						self["tivoinactive"].show()
					else:
						self["tivoactive"].show()
						self["tivoinactive"].hide()
				elif line.startswith("strict_dlna="):
					if line[12:] == "no":
						self["dlnaactive"].hide()
						self["dlnainactive"].show()
					else:
						self["dlnaactive"].show()
						self["dlnainactive"].hide()
			f.close()
		title = _("MiniDLNA Setup")

		for cb in self.onChangedEntry:
			cb(title, status_summary, autostartstatus_summary)

	def setupminidlna(self):
		self.session.openWithCallback(self.updateService, NetworkMiniDLNASetup)

	def minidlnaLog(self):
		self.session.open(NetworkMiniDLNALog)


class NetworkMiniDLNASetup(ConfigListScreen, HelpableScreen, Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		ConfigListScreen.__init__(self, [], session=self.session, on_change=self.changedEntry, fullUI=True)
		self.setTitle(_("MiniDLNA Setup"))
		self.skinName = "NetworkuShareSetup"
		self["key_yellow"] = Label(_("Shares"))
		self["actions"] = ActionMap(["ColorActions"],
		{
			"yellow": self.selectfolders,
		})
		self.updateList()

	def updateList(self, ret=None):
		self.list = []
		self.minidlna_name = NoSave(ConfigText(default=getBoxType(), fixed_size=False))
		self.minidlna_iface = NoSave(ConfigText(fixed_size=False))
		self.minidlna_port = NoSave(ConfigNumber())
		self.minidlna_serialno = NoSave(ConfigNumber())
		self.minidlna_web = NoSave(ConfigYesNo(default=True))
		self.minidlna_inotify = NoSave(ConfigYesNo(default=True))
		self.minidlna_tivo = NoSave(ConfigYesNo(default=True))
		self.minidlna_strictdlna = NoSave(ConfigYesNo(default=True))

		if fileExists("/etc/minidlna.conf"):
			f = open("/etc/minidlna.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("friendly_name="):
					line = line[14:]
					self.minidlna_name = NoSave(ConfigText(default=line, fixed_size=False))
					self.list.append(getConfigListEntry(_("Name") + ":", self.minidlna_name))
				elif line.startswith("network_interface="):
					line = line[18:]
					self.minidlna_iface = NoSave(ConfigText(default=line, fixed_size=False))
					self.list.append(getConfigListEntry(_("Interface") + ":", self.minidlna_iface))
				elif line.startswith("port="):
					line = int(line[5:])
					self.minidlna_port = NoSave(ConfigNumber(default=line))
					self.list.append(getConfigListEntry(_("Port") + ":", self.minidlna_port))
				elif line.startswith("serial="):
					line = int(line[7:])
					self.minidlna_serialno = NoSave(ConfigNumber(default=line))
					self.list.append(getConfigListEntry(_("Serial no") + ":", self.minidlna_serialno))
				elif line.startswith("inotify="):
					if line[8:] == "no":
						default = False
					else:
						default = True
					self.minidlna_inotify = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("Inotify monitoring") + ":", self.minidlna_inotify))
				elif line.startswith("enable_tivo="):
					if line[12:] == "no":
						default = False
					else:
						default = True
					self.minidlna_tivo = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("TiVo support") + ":", self.minidlna_tivo))
				elif line.startswith("strict_dlna="):
					if line[12:] == "no":
						default = False
					else:
						default = True
					self.minidlna_strictdlna = NoSave(ConfigYesNo(default=default))
					self.list.append(getConfigListEntry(_("Strict DLNA") + ":", self.minidlna_strictdlna))
			f.close()
		self["config"].list = self.list

	def keySave(self):
		if fileExists("/etc/minidlna.conf"):
			inme = open("/etc/minidlna.conf", "r")
			out = open("/etc/minidlna.conf.tmp", "w")
			for line in inme.readlines():
				line = line.replace("\n", "")
				if line.startswith("friendly_name="):
					line = ("friendly_name=" + self.minidlna_name.value.strip())
				elif line.startswith("network_interface="):
					line = ("network_interface=" + self.minidlna_iface.value.strip())
				elif line.startswith("port="):
					line = ("port=" + str(self.minidlna_port.value))
				elif line.startswith("serial="):
					line = ("serial=" + str(self.minidlna_serialno.value))
				elif line.startswith("media_dir="):
					line = ("media_dir=" + ", ".join(config.networkminidlna.mediafolders.value))
				elif line.startswith("inotify="):
					if not self.minidlna_inotify.value:
						line = "inotify=no"
					else:
						line = "inotify=yes"
				elif line.startswith("enable_tivo="):
					if not self.minidlna_tivo.value:
						line = "enable_tivo=no"
					else:
						line = "enable_tivo=yes"
				elif line.startswith("strict_dlna="):
					if not self.minidlna_strictdlna.value:
						line = "strict_dlna=no"
					else:
						line = "strict_dlna=yes"
				out.write((line + "\n"))
			out.close()
			inme.close()
		else:
			self.session.open(MessageBox, _("Sorry your MiniDLNA config is missing"), MessageBox.TYPE_INFO)
			self.close()
		if fileExists("/etc/minidlna.conf.tmp"):
			rename("/etc/minidlna.conf.tmp", "/etc/minidlna.conf")
		self.close()

	def selectfolders(self):
		self.session.openWithCallback(self.updateList, MiniDLNASelection)


class MiniDLNASelection(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Select Folders"))
		self.skinName = "uShareSelection"
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText()

		if fileExists("/etc/minidlna.conf"):
			f = open("/etc/minidlna.conf", "r")
			for line in f.readlines():
				line = line.strip()
				if line.startswith("media_dir="):
					line = line[11:]
					self.mediafolders = line
		self.selectedFiles = [str(n) for n in self.mediafolders.split(", ")]
		defaultDir = "/media/"
		self.filelist = MultiFileSelectList(self.selectedFiles, defaultDir, showFiles=False)
		self["checkList"] = self.filelist

		self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ShortcutActions"],
		{
			"cancel": self.exit,
			"red": self.exit,
			"yellow": self.changeSelectionState,
			"green": self.saveSelection,
			"ok": self.okClicked,
			"left": self.left,
			"right": self.right,
			"down": self.down,
			"up": self.up
		}, -1)
		if not self.selectionChanged in self["checkList"].onSelectionChanged:
			self["checkList"].onSelectionChanged.append(self.selectionChanged)
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		idx = 0
		self["checkList"].moveToIndex(idx)
		self.selectionChanged()

	def selectionChanged(self):
		current = self["checkList"].getCurrent()[0]
		if current[2] == True:
			self["key_yellow"].setText(_("De-select"))
		else:
			self["key_yellow"].setText(_("Select"))

	def up(self):
		self["checkList"].up()

	def down(self):
		self["checkList"].down()

	def left(self):
		self["checkList"].pageUp()

	def right(self):
		self["checkList"].pageDown()

	def changeSelectionState(self):
		self["checkList"].changeSelectionState()
		self.selectedFiles = self["checkList"].getSelectedList()

	def saveSelection(self):
		self.selectedFiles = self["checkList"].getSelectedList()
		config.networkminidlna.mediafolders.value = self.selectedFiles
		self.close(None)

	def exit(self):
		self.close(None)

	def okClicked(self):
		if self.filelist.canDescent():
			self.filelist.descent()


class NetworkMiniDLNALog(LogBase):
	def __init__(self, session):
		LogBase.__init__(self, session, "/var/volatile/log/minidlna.log")


class NetworkServicesSummary(Screen):
	def __init__(self, session, parent):
		Screen.__init__(self, session, parent=parent)
		self["title"] = StaticText("")
		self["status_summary"] = StaticText("")
		self["autostartstatus_summary"] = StaticText("")
		self.onShow.append(self.addWatcher)
		self.onHide.append(self.removeWatcher)

	def addWatcher(self):
		self.parent.onChangedEntry.append(self.selectionChanged)
		self.parent.updateService()

	def removeWatcher(self):
		self.parent.onChangedEntry.remove(self.selectionChanged)

	def selectionChanged(self, title, status_summary, autostartstatus_summary):
		self["title"].text = title
		self["status_summary"].text = status_summary
		self["autostartstatus_summary"].text = autostartstatus_summary


class NetworkPassword(Setup):
	def __init__(self, session):
		self.password = NoSave(ConfigPassword(default=""))
		Setup.__init__(self, session=session, setup=None)
		self.skinName = "Setup"
		self.title = _("Password Setup")
		self["key_yellow"] = StaticText(_("Random Password"))
		self["passwordActions"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.newRandom, _("Randomly generate a password"))
		}, prio=0, description=_("Password Actions"))
		self.user = "root"

	def newRandom(self):
		passwdChars = string.ascii_letters + string.digits
		passwdLength = 10
		self.password.value = "".join(Random().sample(passwdChars, passwdLength))
		self["config"].invalidateCurrent()

	def createSetup(self):
		instructions = _("Setting a network password is mandatory in OpenViX %s if you wish to use network services. \nTo set a password using the virtual keyboard press the 'text' button on your remote control.") % getImageVersion()
		self.list.append(getConfigListEntry(_('New password'), self.password, instructions))
		self['config'].list = self.list

	def keySave(self):
		password = self.password.value
		if not password:
			self.session.open(MessageBox, _("The password can not be blank."), MessageBox.TYPE_ERROR)
			return
		# print("[NetworkPassword] Changing the password for %s to %s" % (self.user,self.password.value))
		self.container = eConsoleAppContainer()
		self.container.appClosed.append(self.runFinished)
		self.container.dataAvail.append(self.dataAvail)
		retval = self.container.execute(*("/usr/bin/passwd", "/usr/bin/passwd", self.user))
		if retval:
			message = _("Unable to change password")
			self.session.open(MessageBox, message, MessageBox.TYPE_ERROR)
		else:
			message = _("Password changed")
			self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=5)
			self.close()

	def dataAvail(self, data):
		# print("[NetworkPassword][dataAvail] data is:", data)
		if data.endswith(b"password: "):
			self.container.write("%s\n" % self.password.value)

	def runFinished(self, retval):
		del self.container.dataAvail[:]
		del self.container.appClosed[:]
		del self.container
		self.close()
