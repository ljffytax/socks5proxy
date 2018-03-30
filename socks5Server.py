#!/usr/bin/python
#coding:utf-8

import socket, sys, select, SocketServer, struct, time, zlib, itertools
KEY = 'yourkey'

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
		n = '%04d' %l
		return 'LN' + n + xdata + '1000'

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
					print e
					break
	def handle(self):
		try:
			#print 'socks connection from ', self.client_address
			sock = self.connection
			# 1. Version
			buf = self.recvDataBlock(sock)
			if not buf:
				raise DataError('data error, Zero buf')
			data = self.coder.decode(buf)
			#data = sock.recv(2) # Why 262 ?
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
						raise DataError('data error1')
					data = self.coder.decode(buf)
					if len(data) < 4:
						raise DataError('data error')
					mode = ord(data[1])
					addrtype = ord(data[3])
					if addrtype == 1:       # IPv4
						addr = socket.inet_ntoa(data[4:8])
						port = struct.unpack('>H', data[8:10])
					elif addrtype == 3:     # Domain name
						addr = socket.inet_ntoa(data[5:(5+ord(data[4]))])
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
						print "Connect to web server error", e
						# Connection refused
						reply = '\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00'
					sock.sendall(self.coder.encode(reply))
					# 3. Transfering
					if reply[1] == '\x00':  # Success
						if mode == 1:    # 1. Tcp connect
							self.handle_tcp(sock, remote)
		except socket.error:
			print 'socket error'
		except DataError as e:
			print e

#+--+----+--------------+----+
#|LN|XXXX|     DATA     |1000|
#+--+----+--------------+----+
	def recvDataBlock (self, socket):
		data = ''
		head = socket.recv(6)
		if not head:
			return None
		if len(head) < 6:
			t= socket.recv(6-len(head))
			head = head+t
		flag = head[:2]
		l = 0
		k = 0
		#logger.debug ("Flag:", head)
		if flag == 'LN':
			l = int(head[2:])
			k = l
		else:
		#	logger.error ("Bad data Block!!!")
			return None
		#logger.debug ("len is %d", l)
		while 1:
			t = socket.recv(l+4)
			if not t:
				return None
			data = data + t
			if len(data) >= k+4:
				break
			l = l-len(t)
		data = data[:len(data)-4]
		return data		

def main():
	server = ThreadingTCPServer(('0.0.0.0', 9880), Socks5Server)
	server.serve_forever()
if __name__ == '__main__':
	main()
