import { defineStore } from 'pinia'
import opnformConfig from '~/opnform.config.js'

function notionApiFetch (entityId, type = 'table') {
  const apiUrl = opnformConfig.notion.worker
  return useFetch(`${apiUrl}/${type}/${entityId}`)
}

function fetchNotionDatabasePages (databaseId) {
  return notionApiFetch(databaseId)
}

function fetchNotionPageContent (pageId) {
  return notionApiFetch(pageId, 'page')
}

export const useNotionCmsStore = defineStore('notion_cms', {
  state: () => ({
    databases: {},
    pages: {},
    pageContents: {},
    slugToIdMap: {},
    loading: false,
  }),

  actions: {
    _formatId (id) {
      return id.replaceAll('-', '')
    },

    setSlugToIdMap (slug, pageId) {
      if (!slug) return
      this.slugToIdMap[slug.toLowerCase()] = this._formatId(pageId)
    },

    async loadDatabase (databaseId) {
      if (this.databases[databaseId]) {
        return
      }

      this.loading = true
      try {
        const response = await fetchNotionDatabasePages(databaseId)
        if (response.data.value && Array.isArray(response.data.value)) {
          this.databases[databaseId] = response.data.value.map(page => this._formatId(page.id))
          response.data.value.forEach(page => {
            const formattedId = this._formatId(page.id)
            this.pages[formattedId] = {
              ...page,
              id: formattedId,
            }
            const slug = page.Slug ?? page.slug ?? null
            if (slug) {
              this.setSlugToIdMap(slug, page.id)
            }
          })
        } else {
          console.warn('Received unexpected data structure for database:', databaseId, response.data.value)
          this.databases[databaseId] = []
        }
      } catch (error) {
        console.error(error)
        throw error
      } finally {
        this.loading = false
      }
    },

    async loadPage (pageId) {
      const formattedPageId = this._formatId(pageId)
      if (this.pageContents[formattedPageId]) {
        return 'in already here'
      }

      this.loading = true
      try {
        const response = await fetchNotionPageContent(pageId)
        this.pageContents[formattedPageId] = response.data.value
        return 'in finishg'
      } catch (error) {
        console.error(error)
        throw error
      } finally {
        this.loading = false
      }
    },

    loadPageBySlug (slug) {
      if (!this.slugToIdMap[slug.toLowerCase()]) return
      return this.loadPage(this.slugToIdMap[slug.toLowerCase()])
    },

    getPage (pageId) {
      if (!pageId) return null
      const formattedId = this._formatId(pageId)
      return {
        ...this.pages[formattedId],
        blocks: this.getPageBody(formattedId),
      }
    },

    getPageBody (pageId) {
      if (!pageId) return null
      const formattedId = this._formatId(pageId)
      return this.pageContents[formattedId]
    },

    getPageBySlug (slug) {
      if (!slug) return
      const pageId = this.slugToIdMap[slug.toLowerCase()]
      return this.getPage(pageId)
    },
  },

  getters: {
    databasePages: (state) => (databaseId) => {
      return state.databases[databaseId]?.map(id => state.pages[id]) || []
    },

    pageContent: (state) => (pageId) => {
      if (!pageId) return null
      const formattedId = pageId.replaceAll('-', '')
      return state.pageContents[formattedId]
    },

    pageBySlug: (state) => {
      return (slug) => {
        if (!slug) return null
        const pageId = state.slugToIdMap[slug.toLowerCase()]
        if (!pageId) return null

        const formattedId = pageId.replaceAll('-', '')
        const pageData = state.pages[formattedId]
        const pageContent = state.pageContents[formattedId]

        if (!pageData) return null

        return {
          ...pageData,
          blocks: pageContent,
        }
      }
    },
  },
})