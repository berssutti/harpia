import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import App from './app.vue';

describe('App Layout Navigation Redesign', () => {
  it('should NOT render the sidebar', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          NuxtLink: true,
          NuxtPage: true,
        },
      },
    });
    expect(wrapper.find('.sidebar').exists()).toBe(false);
  });

  it('should render the top header and dropdown menu navigation', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          NuxtLink: true,
          NuxtPage: true,
        },
      },
    });
    // Header checks
    expect(wrapper.find('.app-header').exists()).toBe(true);

    // Dropdown trigger/menu check
    expect(wrapper.find('.dropdown-trigger').exists()).toBe(true);
  });

  it('should render the app footer with the system name', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          NuxtLink: true,
          NuxtPage: true,
        },
      },
    });
    // Footer checks
    expect(wrapper.find('.app-footer').exists()).toBe(true);
    expect(wrapper.find('.footer-title').text()).toContain('🦅 HARPIA');
  });
});
