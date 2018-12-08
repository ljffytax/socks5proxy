#!/usr/bin/python
#coding:utf-8

import socket, sys, select, SocketServer, struct, time, zlib, itertools
import os, signal, threading, time

SERVERIP = "1.2.3.4"
SERVERPOT = 8888
KEY = "yourkey"
QUITED = 0
SVR = None
HTTPHeader = '''GET / HTTP/1.1\r
Host: www.baidu.com\r
User-Agent: Mozilla/5.0 (Windows NT 6.1; rv:19.0) Gecko/20100101 Firefox/19.0\r
Accept: text/html\r
Connection: keep-alive\r\n\r\n'''

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


class ThreadingTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer): pass
class Socks5Server(SocketServer.StreamRequestHandler):
	coder = dataEcoder(KEY)

	def handle_tcp(self, sock, remote):
		fdset = [sock, remote]
		while True:
			r, w, e = select.select(fdset, [], [])
			if sock in r:
				buf = sock.recv(4096)
				if not buf:
					break
				try:
					remote.sendall(self.coder.encode(buf))
				except Exception as e:
					print e
					break
			if remote in r:
				buf = self.recvDataBlock(remote)
				if not buf:
					break
				try:
					sock.sendall(self.coder.decode(buf))
				except Exception as e:
					print e
					break
	
	def handle(self):
		try:
			#print 'socks connection from ', self.client_address
			sock = self.connection
			reply = b"\x05\x00\x00\x01"
			try:
				#if mode == 1:  # 1. Tcp connect
				remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				remote.connect((SERVERIP, SERVERPOT))
			except socket.error as e:
				# Connection refused
				print 'Connect to proxy sever error!',e
				reply = '\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00'
				sock.send(reply)
			# 3. Transfering
			if reply[1] == '\x00':  # Success
				#if mode == 1:    # 1. Tcp connect
				#To avoid data blocked by GFW, we should send a HTTP header befor the real data
				remote.sendall(HTTPHeader)
				self.handle_tcp(sock, remote)
		except socket.error:
			print 'socket error'

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

def quit(signum, frame):
	print "Got quit signal...\n"
	global QUITED 
	QUITED = 1

def quitThread ():
	global QUITED
	while True:
		if QUITED:
			SVR.shutdown()
			break
		time.sleep(1)

def main():
	print "Listening on 1515..."
	global SVR
	signal.signal(signal.SIGINT, quit)
	signal.signal(signal.SIGTERM, quit)
	server = ThreadingTCPServer(('', 1515), Socks5Server)
	server.daemon_threads = True
	SVR = server
	q = threading.Thread (target = quitThread)
	q.start()
	server.serve_forever()
	server.server_close()

if __name__ == '__main__':
	main()
