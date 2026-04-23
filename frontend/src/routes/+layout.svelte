<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import {
		LayoutDashboard,
		Library,
		FolderTree,
		History,
		Settings,
		Database
	} from 'lucide-svelte';

	let { children } = $props();

	const navItems = [
		{ name: 'Dashboard', href: '/', icon: LayoutDashboard },
		{ name: 'Inventory', href: '/inventory', icon: Library },
		{ name: 'File Tracking', href: '/tracking', icon: FolderTree },

		{ name: 'Restores', href: '/restores', icon: History }
	];
</script>

<div class="app-container">
	<nav>
		<h2><Database size={24} color="#3498db" /> TapeHoard</h2>
		<ul>
			{#each navItems as item}
				<li>
					<a href={item.href} class:active={$page.url.pathname === item.href}>
						<item.icon size={20} />
						{item.name}
					</a>
				</li>
			{/each}
		</ul>
		<div style="margin-top: auto;">
			<ul>
				<li>
					<a href="/settings" class:active={$page.url.pathname === '/settings'}>
						<Settings size={20} />
						Settings
					</a>
				</li>
			</ul>
		</div>
	</nav>
	<main>
		{@render children()}
	</main>
</div>
