import { defineStore } from 'pinia'

export const useConsoleStore = defineStore('console', {
  state: () => ({
    messages: []
  }),
  actions: {
    addMessage(text, type = 'info') {
      this.messages.push({
        id: Date.now() + Math.random().toString(36).substr(2, 9),
        timestamp: new Date().toLocaleTimeString(),
        text,
        type
      });
    },
    clearMessages() {
      this.messages = [];
    }
  }
})