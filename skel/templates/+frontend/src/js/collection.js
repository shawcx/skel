// records by their key, which tell listeners when they're added, changed or removed:
//   messages.addEventListener('add', (event) => show(event.detail))
export default class Collection extends EventTarget {
    constructor(key = 'id') {
        super()
        this.key     = key
        this.records = new Map()
    }

    get size() {
        return this.records.size
    }

    get(id) {
        return this.records.get(id)
    }

    [Symbol.iterator]() {
        return this.records.values()
    }

    add(record) {
        // adding a record that's here already changes it
        if (this.records.has(record[this.key])) {
            this.update(record)
            return
        }
        this.records.set(record[this.key], {...record})
        this.emit('add', this.get(record[this.key]))
    }

    update(record) {
        let existing = this.get(record[this.key])
        if (existing) {
            Object.assign(existing, record)
            this.emit('change', existing)
        }
    }

    remove(id) {
        let existing = this.get(id)
        if (existing) {
            this.records.delete(id)
            this.emit('remove', existing)
        }
    }

    emit(type, record) {
        this.dispatchEvent(new CustomEvent(type, {detail: record}))
    }
}
