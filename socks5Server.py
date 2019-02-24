#!/usr/bin/python
#coding:utf-8

import socket, sys, select, SocketServer, struct, time, zlib, itertools
import os, signal, threading, atexit
import logging
from signal import SIGTERM

KEY = 'yourkey'
SVR = None
QUITED = 0

logger = logging.getLogger("rootloger")
LOG_FILE = "/var/log/SocketServer.log"

def init_loger():
	logger.setLevel(logging.INFO)
	handler = logging.FileHandler(LOG_FILE)
	handler.setLevel(logging.INFO)
	#formatter = logging.Formatter('%(asctime)s-%(levelname)s-%(message)s')
	formatter = logging.Formatter("%(asctime)s;%(levelname)s;%(message)s",
									"%Y-%m-%d %H:%M:%S")
	handler.setFormatter(formatter)
	logger.addHandler(handler)

class dataEcoder:
	def __init__(self, k):
		self.KEY = k

	def xor(self, s, key):
		key = key * (len(s) / len(key) + 1)
		return ''.join(chr(ord(x) ^ ord(y)) for (x,y) in itertools.izip(s, key))

	def zipXorData(self, data):
		zdata = zlib.compress(data,4)
		xdata = self.xor(zdata, self.KEY)
		l = len(xdata)
		if l>9999:
			return None
		n = struct.pack('>H', l)
		return 'LN' + n + xdata + '00'

	def unzipXorData(self, data):
		xdata = self.xor(data, self.KEY)
		zdata = zlib.decompress(xdata)
		return zdata

	def encode(self, data):
		edata = self.zipXorData(data)
		return edata

	def decode(self, data):
		ddata = self.unzipXorData(data)
		return ddata

class DataError(Exception):
	def __init__(self, ErrorInfo):
		super(DataError, self).__init__()
		self.errorinfo = ErrorInfo
	def __str__(self):
		return self.errorinfo

class ThreadingTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer): pass
class Socks5Server(SocketServer.StreamRequestHandler):
	coder = dataEcoder(KEY)
	timeout = 10
	def handle_tcp(self, sock, remote):
		fdset = [sock, remote]
		while True:
			r, w, e = select.select(fdset, [], [])
			if sock in r:
				buf = self.recvDataBlock(sock)
				if not buf:
					break
				try:
					remote.sendall(self.coder.decode(buf))
				except:
					break
			if remote in r:
				buf = remote.recv(4096)
				if not buf:
					break
				try:
					sock.sendall(self.coder.encode(buf))
				except socket.error as e:
					logger.error("%s", e)
					break
	def handle(self):
		try:
			#print 'socks connection from ', self.client_address
			sock = self.connection
			#Recive the HTTH header and then drop it
			buf = self.recvHTTPHeader(sock)
			if not buf:
				raise DataError('HTTP header data error, Zero buf')
			buf = self.recvDataBlock(sock)
			if not buf:
				raise DataError('data error, Zero buf')
			data = self.coder.decode(buf)
			if b'\x05' == data[0]:  #socks5
				nmethods = ord(data[1])
				if len(data) != nmethods + 2:
					raise DataError('data error')
				else:
					data = self.coder.encode(b"\x05\x00")
					sock.send(data)
					# 2. Request
					buf = self.recvDataBlock(sock)
					if not buf:
						raise DataError('data error, not enough data')
					data = self.coder.decode(buf)
					if len(data) < 4:
						raise DataError('data error, bad data block')
					mode = ord(data[1])
					addrtype = ord(data[3])
					if addrtype == 1:       # IPv4
						addr = socket.inet_ntoa(data[4:8])
						port = struct.unpack('>H', data[8:10])
					elif addrtype == 3:     # Domain name
						addr = data[5:(5+ord(data[4]))]
						port = struct.unpack('>H', data[(5+ord(data[4])):(7+ord(data[4]))])
					reply = b"\x05\x00\x00\x01"
					try:
						if mode == 1:  # 1. Tcp connect
							remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
							remote.connect((addr, port[0]))
							#print 'Tcp connect to', addr, port[0]
						else:
							reply = b"\x05\x07\x00\x01" # Command not supported
						local = remote.getsockname()
						reply += socket.inet_aton(local[0]) + struct.pack(">H", local[1])
					except socket.error as e:
						logger.error("Connect to web server error: %s", e)
						# Connection refused
						reply = '\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00'
					sock.sendall(self.coder.encode(reply))
					# 3. Transfering
					if reply[1] == '\x00':  # Success
						if mode == 1:    # 1. Tcp connect
							self.handle_tcp(sock, remote)
		except socket.error as e:
			logger.error("%s", e)
		except DataError as e:
			logger.error("%s", e)

	def recvHTTPHeader (self, socket):
		header = ''
		data = ''
		i = 0
		n = 0
		while 1:
			while n < 3:
				try:
					data = socket.recv(1)
					break
				except Exception as e:
					err = e.args[0]
					if err == 'timed out':
						n = n + 1
					else:
						break
			if not data:
				break
			else:
				i = i + 1
				header = header + data
				if i > 3 and data == '\n' and header[i-2] == '\r' and header[i-3] == '\n':
					break
		return i

#+--+--+--------------+--+
#|LN|XX|     DATA     |00|
#+--+--+--------------+--+
	def recvDataBlock (self, socket):
		data = ''
		i = 0
		while i < 3:
			try:
				head = socket.recv(4)
				break
			except Exception as e:
				err = e.args[0]
				if err == 'timed out':
					i = i + 1
				else:
					break
		if not head:
			return None
		if len(head) < 4:
			t= socket.recv(4-len(head))
			head = head+t
		flag = head[:2]
		l = 0
		k = 0
		if flag == 'LN':
			l = struct.unpack('>H',head[2:])
			l = l[0]
			k = l
		else:
			return None
		while 1:
			t = socket.recv(l+2)
			if not t:
				return None
			data = data + t
			if len(data) >= k+2:
				break
			l = l-len(t)
		if data[len(data)-2:] == "00":
			data = data[:len(data)-2]
		else:
			data = None
		return data		

def daemonize(pidfile):
	"""
	do the UNIX double-fork magic, see Stevens' "Advanced 
	Programming in the UNIX Environment" for details (ISBN 0201563177)
	http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
	"""
	stdin='/dev/null'
	stdout='/dev/null'
	stderr='/dev/null'
	try: 
		pid = os.fork() 
		if pid > 0:
			# exit first parent
			sys.exit(0) 
	except OSError, e:
		logger.critical("fork #1 failed: %s",e) 
		sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
		sys.exit(1)

	# decouple from parent environment
	os.chdir("/") 
	os.setsid() 
	os.umask(0) 

	# do second fork
	try: 
		pid = os.fork() 
		if pid > 0:
			# exit from second parent
			sys.exit(0) 
	except OSError, e: 
		logger.critical("fork #2 failed: %s",e) 
		sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
		sys.exit(1) 

	# redirect standard file descriptors
	sys.stdout.flush()
	sys.stderr.flush()
	si = file(stdin, 'r')
	so = file(stdout, 'a+')
	se = file(stderr, 'a+', 0)
	os.dup2(si.fileno(), sys.stdin.fileno())
	os.dup2(so.fileno(), sys.stdout.fileno())
	os.dup2(se.fileno(), sys.stderr.fileno())

	# write pidfile
	atexit.register(delpid,pidfile,)
	pid = str(os.getpid())
	file(pidfile,'w+').write("%s\n" % pid)

def delpid(pidfile):
	os.remove(pidfile)
	
def startServerDeamo(pidfile):
	"""
	Start the daemon
	"""
	# Check for a pidfile to see if the daemon already runs
	try:
		pf = file(pidfile,'r')
		pid = int(pf.read().strip())
		pf.close()
	except IOError:
		pid = None
	if pid:
		message = "pidfile %s already exist. Daemon already running?\n"
		logger.error("pidfile is already exist")
		sys.stderr.write(message % pidfile)
		sys.exit(1)
	# Start the daemon
	daemonize(pidfile)
	serverStart()

def stopServerDeamo(pidfile):
	"""
	Stop the daemon
	"""
	# Get the pid from the pidfile
	try:
		pf = file(pidfile,'r')
		pid = int(pf.read().strip())
		pf.close()
	except IOError:
		pid = None

	if not pid:
		message = "pidfile %s does not exist. Daemon not running?\n"
		logger.error("pidfile does not exist")
		sys.stderr.write(message % pidfile)
		return 

	# Try killing the daemon process
	try:
		while 1:
			os.kill(pid, SIGTERM)
			time.sleep(2)
	except OSError, err:
		err = str(err)
		if err.find("No such process") > 0:
			if os.path.exists(pidfile):
				os.remove(pidfile)
		else:
			logger.error("%s", str(err))
			sys.exit(1)

def quit(signum, frame):
	logger.info("Got quit signal\n")
	global QUITED 
	QUITED = 1

def quitThread ():
	global QUITED
	while True:
		if QUITED:
			SVR.shutdown()
			break
		time.sleep(1)

def serverStart():
	global SVR
	signal.signal(signal.SIGINT, quit)
	signal.signal(signal.SIGTERM, quit)
	server = ThreadingTCPServer(('0.0.0.0', 9880), Socks5Server)
	server.daemon_threads = True
	SVR = server
	q = threading.Thread (target = quitThread)
	q.start()
	server.serve_forever()
	server.server_close()

if __name__ == "__main__":
	pidf = "/var/run/socks5Server.pid"
	init_loger()
	if len(sys.argv) >= 2:
		if 'start' == sys.argv[1]:
			logger.info("server start: %s", sys.argv[1])
			startServerDeamo(pidf)
		elif 'stop' == sys.argv[1]:
			stopServerDeamo(pidf)
		elif 'restart' == sys.argv[1]:
			logger.error("bad args: %s", sys.argv[1])
			print "You should run stop and then run start..."
		else:
			logger.error("Unknown command: %s", sys.argv[1])
			print "Unknown command"
			sys.exit(2)
		sys.exit(0)
	else:
		print "usage: %s start|stop|restart" % sys.argv[0]
		sys.exit(2)
