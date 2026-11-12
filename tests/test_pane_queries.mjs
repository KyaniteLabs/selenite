// Exercise revision changes with the pinned real @tanstack/query-core package.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

const root = process.env.TANSTACK_QUERY_CORE
const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8')

if (!root) throw new Error('Set TANSTACK_QUERY_CORE to the unpacked query-core package')

test('all five revision-keyed queries keep their last data during event refreshes', async () => {
    const { QueryClient, QueryObserver } = await import(pathToFileURL(`${root}/build/modern/index.js`))
    const queries = [...source.matchAll(/const (overview|events|proposal|cleanse|fake) = useQuery\(\{([^\n]+)\}\)/g)]
    assert.equal(queries.length, 5)
    assert.ok(queries.every(([, , options]) => options.includes('placeholderData: prev => prev')))

    const client = new QueryClient()
    for (const [name] of queries) {
      let revision = 0
      let fetch = 0
      const options = () => ({
        queryKey: ['selenite', name, revision],
        queryFn: async () => ({ name, fetch: ++fetch }),
        placeholderData: prev => prev
      })
      const observer = new QueryObserver(client, options())
      const unsubscribe = observer.subscribe(() => {})
      await new Promise(resolve => setImmediate(resolve))
      assert.deepEqual(observer.getCurrentResult().data, { name, fetch: 1 })
      revision++ // a validated live event creates the next revision key
      observer.setOptions(options()) // React Query updates observer options on rerender
      assert.deepEqual(observer.getCurrentResult().data, { name, fetch: 1 })
      assert.equal(observer.getCurrentResult().isPending, false)
      unsubscribe()
    }
    client.clear()
  })
