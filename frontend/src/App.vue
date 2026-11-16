<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span>价签柜</span> · Pricecab
        <small>改价预约生效 · 现行价签 · 销售对账</small>
      </div>
      <nav class="nav">
        <router-link to="/">总览</router-link>
        <router-link to="/tickets">改价单</router-link>
        <router-link to="/apply">生效应用</router-link>
        <router-link to="/prices">现行价签</router-link>
        <router-link to="/reconcile">销售对账</router-link>
      </nav>
    </header>
    <router-view />
  </div>
</template>
