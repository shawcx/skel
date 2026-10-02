'use strict'

var $ = require('jquery')

class Socket {
    constructor(_options) {
        this.options = {
            path      : 'ws',
            timeout   : 0.9375,
            maxtime   : 60,
            ping      : 300,
            onopen    : function() {},
            onmessage : function(msg) {}
        }

        if (_options) {
            for(const key of Object.keys(_options)) {
                this.options[key] = _options[key]
            }
        }

        let protocol = location.protocol.replace('http','ws')
        this.wsurl = `${protocol}//${location.host}/${this.options.path}`

        this.timeout = this.options.timeout
        this.connect()
    }

    connect() {
        this.ws = new WebSocket(this.wsurl)

        this.ws.onopen = (event) => {
            this.timeout = this.options.timeout
            if (this.options.ping) {
                this.interval = setInterval(() => {
                    this.ws.send('ping')
                }, 1000 * this.options.ping)
            }
            this.options.onopen()
        }

        this.ws.onmessage = (event) => {
            let msg
            try {
                msg = JSON.parse(event.data)
            } catch (e) {
                console.warn('Ignoring non-JSON message:', event.data)
                return
            }
            this.options.onmessage(msg)
        }

        this.ws.onerror = (event) => {
            clearInterval(this.interval)
            this.timeout = this.timeout * 2
        }

        this.ws.onclose = (event) => {
            console.log('Closing socket...')
            if (event.code == 4004) {
                window.location.reload()
            }

            clearInterval(this.interval)

            if (this.timeout > this.options.maxtime) {
                return
            }

            setTimeout(() => {
                    this.connect()
                    return
                }, 1000 * this.timeout)
        }
    }

    sendraw(message) {
        this.ws.send(message)
    }

    send(message) {
        this.ws.send(JSON.stringify(message))
    }
}

module.exports = Socket
