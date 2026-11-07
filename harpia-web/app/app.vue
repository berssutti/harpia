<template>
  <div class="app-layout">
    <header class="app-header">
      <div class="header-left"></div>
      <div class="nav-dropdown-container">
        <button class="dropdown-trigger" @click="toggleDropdown" aria-label="Menu de Navegação">
          <span class="trigger-icon">☰</span>
          <span class="trigger-text label-caps">Navegar</span>
        </button>
        <transition name="dropdown-fade">
          <div v-if="isDropdownOpen" class="dropdown-menu">
            <NuxtLink to="/" class="dropdown-item" @click="closeDropdown">
              <span class="icon">🎯</span>
              <span class="label-caps">Painel</span>
            </NuxtLink>
            <NuxtLink to="/settings" class="dropdown-item" @click="closeDropdown">
              <span class="icon">⚙️</span>
              <span class="label-caps">Configurações</span>
            </NuxtLink>
          </div>
        </transition>
      </div>
      <div class="header-spacer"></div>
    </header>
    <main class="main-content">
      <div class="page-container">
        <NuxtPage />
      </div>
    </main>
    <footer class="app-footer">
      <span class="footer-title label-caps">🦅 HARPIA</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';

const isDropdownOpen = ref(false);

const toggleDropdown = (event: Event) => {
  event.stopPropagation();
  isDropdownOpen.value = !isDropdownOpen.value;
};

const closeDropdown = () => {
  isDropdownOpen.value = false;
};

const handleOutsideClick = (event: MouseEvent) => {
  const container = document.querySelector('.nav-dropdown-container');
  if (container && !container.contains(event.target as Node)) {
    closeDropdown();
  }
};

onMounted(() => {
  window.addEventListener('click', handleOutsideClick);
});

onUnmounted(() => {
  window.removeEventListener('click', handleOutsideClick);
});
</script>

<style>
.app-layout {
  background-color: var(--bg-color);
  color: var(--text-main);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  width: 100vw;
}

.app-header {
  align-items: center;
  background-color: var(--surface-1);
  border-bottom: 1px solid var(--border-color);
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  height: 64px;
  padding: 0 24px;
}

.header-left {
  display: block;
}

.nav-dropdown-container {
  position: relative;
}

.dropdown-trigger {
  align-items: center;
  background-color: var(--surface-2);
  border: 1px solid var(--border-color);
  color: var(--text-main);
  cursor: pointer;
  display: flex;
  font-weight: 600;
  gap: 8px;
  padding: 8px 16px;
  transition: all 0.2s ease;
}

.dropdown-trigger:hover {
  background-color: rgba(255, 184, 0, 0.05);
  border-color: var(--primary);
  color: var(--primary);
}

.trigger-icon {
  font-size: 18px;
}

.dropdown-menu {
  background-color: var(--surface-1);
  border: 1px solid var(--border-color);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -2px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  left: 50%;
  padding: 8px 0;
  position: absolute;
  top: calc(100% + 8px);
  transform: translateX(-50%);
  width: 200px;
  z-index: 100;
}

.dropdown-item {
  align-items: center;
  border-left: 2px solid transparent;
  color: var(--text-muted);
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  text-decoration: none;
  transition: all 0.2s ease;
}

.dropdown-item:hover {
  background-color: rgba(255, 184, 0, 0.05);
  color: var(--primary);
}

.dropdown-item.router-link-active {
  background-color: var(--surface-2);
  border-left-color: var(--primary);
  color: var(--primary);
}

.dropdown-fade-enter-active,
.dropdown-fade-leave-active {
  transition: all 0.2s ease;
}

.dropdown-fade-enter-from,
.dropdown-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}

.header-spacer {
  display: block;
}

.main-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.page-container {
  flex: 1;
  overflow: hidden;
  padding: 32px;
}

.app-footer {
  align-items: center;
  background-color: var(--surface-1);
  border-top: 1px solid var(--border-color);
  display: flex;
  height: 48px;
  justify-content: center;
}

.footer-title {
  color: var(--text-muted);
  font-size: var(--fs-label);
  font-weight: 600;
  letter-spacing: 0.05em;
}
</style>
