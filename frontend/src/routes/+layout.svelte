<script lang="ts">
        // @ts-ignore
        import '../app.css';
        // @ts-ignore
        import { page } from '$app/stores';	import {
		LayoutDashboard,
		Library,
		FolderTree,
		History,
		Settings,
		Database,
		CassetteTape,
		Activity,
		ChevronLeft,
		ChevronRight
	} from 'lucide-svelte';
	import { cn } from '$lib/utils';
	import { Toaster } from 'svelte-sonner';
	import ScanStatusOverlay from '$lib/components/ScanStatusOverlay.svelte';

	let { children } = $props();

	const navItems = [
		{ name: 'Overview', href: '/', icon: LayoutDashboard },
		{ name: 'Virtual Index', href: '/index-browser', icon: Library },
		{ name: 'Live Filesystem', href: '/tracking', icon: FolderTree },
		{ name: 'Jobs', href: '/jobs', icon: Activity },
		{ name: 'Media Inventory', href: '/inventory', icon: CassetteTape },
		{ name: 'Data Recovery', href: '/restores', icon: History }
	];

	let isSidebarOpen = $state(true);
	let showShortcuts = $state(false);

	function handleGlobalKeyDown(e: KeyboardEvent) {
		if (e.key === '?' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
			showShortcuts = !showShortcuts;
		}
		if (showShortcuts && e.key === 'Escape') {
			showShortcuts = false;
		}

		// Navigation Shortcuts (Single keys only, no modifiers)
		if (!['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName) && !e.ctrlKey && !e.metaKey && !e.altKey) {
			if (e.key === 'd') window.location.href = '/';
			if (e.key === 'i') window.location.href = '/index-browser';
			if (e.key === 't') window.location.href = '/tracking';
			if (e.key === 'a') window.location.href = '/jobs';
			if (e.key === 'm') window.location.href = '/inventory';
			if (e.key === 'r') window.location.href = '/restores';
			if (e.key === 's') window.location.href = '/settings';
		}
	}
</script>

<svelte:window onkeydown={handleGlobalKeyDown} />

<Toaster position="top-left" richColors />
<ScanStatusOverlay />

<!-- Shortcuts Overlay -->
{#if showShortcuts}
	<div class="fixed inset-0 z-[1000] bg-black/90 backdrop-blur-md flex items-center justify-center p-6 animate-in fade-in duration-300" onclick={() => showShortcuts = false} role="presentation">
		<div class="w-[500px] bg-bg-secondary border border-border-color shadow-2xl rounded-2xl p-10 flex flex-col gap-8" onclick={(e) => e.stopPropagation()} role="dialog">
			<header>
				<h2 class="text-2xl font-black text-text-primary uppercase tracking-tighter flex items-center gap-3">
					<span class="p-2 bg-action-color/10 rounded-lg text-action-color"><Settings size={24} /></span>
					Fleet Command Shortcuts
				</h2>
				<p class="text-[11px] font-bold text-text-secondary uppercase tracking-widest mt-2 opacity-60">Universal system navigation & control.</p>
			</header>

			<div class="grid grid-cols-2 gap-x-12 gap-y-6">
				<div class="space-y-4">
					<h3 class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Navigation</h3>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Overview</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">D</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Virtual Index</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">I</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Live Filesystem</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">T</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Jobs</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">A</kbd></div>
				</div>
				<div class="space-y-4">
					<h3 class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Operations</h3>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Media Inventory</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">M</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Data Recovery</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">R</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">System Settings</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">S</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-bold text-text-primary">Close Menu</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-[10px] mono">ESC</kbd></div>
				</div>
			</div>

			<footer class="pt-6 border-t border-border-color flex justify-center">
				<p class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 italic">Press '?' at any time to toggle this command set.</p>
			</footer>
		</div>
	</div>
{/if}

<div class="app-container flex h-screen w-full overflow-hidden bg-bg-primary text-text-primary font-sans selection:bg-action-color/30">
	<!-- SIDEBAR -->
	<aside
		class={cn(
			"sidebar flex flex-col border-r border-border-color bg-bg-secondary transition-all duration-300 relative z-50 shadow-2xl shrink-0",
			isSidebarOpen ? "w-64" : "w-20"
		)}
	>
		<!-- LOGO AREA -->
		<div class={cn(
			"flex h-20 items-center border-b border-border-color bg-bg-tertiary/30 shrink-0 overflow-hidden transition-all duration-300",
			isSidebarOpen ? "px-6" : "px-0 justify-center"
		)}>
			<div class="flex items-center gap-3">
				<div class="flex h-10 w-10 items-center justify-center rounded-xl bg-action-color text-white shadow-lg shadow-action-color/20 shrink-0">
					<Database size={22} strokeWidth={2.5} />
				</div>
				{#if isSidebarOpen}
					<div class="flex flex-col animate-in fade-in slide-in-from-left-2 duration-300">
						<span class="text-lg font-black uppercase tracking-tighter leading-none">TapeHoard</span>
						<span class="text-[9px] font-bold uppercase tracking-[0.2em] text-text-secondary opacity-60">LTO Archival</span>
					</div>
				{/if}
			</div>
		</div>

		<!-- NAVIGATION -->
		<nav class="flex-1 py-4 overflow-y-auto overflow-x-hidden">
			{#each navItems as item}
				{@const isActive = $page.url.pathname === item.href || ($page.url.pathname.startsWith(item.href) && item.href !== '/')}
				<a
					href={item.href}
					class={cn(
						"group flex items-center transition-all w-full border-l-4 h-12",
						isSidebarOpen ? "px-6 gap-4" : "px-0 justify-center gap-0",
						isActive
							? "bg-action-color/10 text-text-primary border-l-action-color"
							: "text-text-secondary hover:bg-white/[0.03] hover:text-text-primary border-l-transparent"
					)}
					title={!isSidebarOpen ? item.name : ''}
				>
					<item.icon size={18} class={cn("shrink-0", isActive ? "text-action-color" : "text-text-secondary group-hover:text-action-color")} />
					{#if isSidebarOpen}
						<span class="truncate text-[12px] font-bold uppercase tracking-wider animate-in fade-in slide-in-from-left-2 duration-300">{item.name}</span>
					{/if}
				</a>
			{/each}
		</nav>

		<!-- FOOTER ACTIONS -->
		<div class="border-t border-border-color bg-bg-tertiary/10 shrink-0 flex flex-col">
			<a
				href="/settings"
				class={cn(
					"group flex items-center transition-all w-full border-l-4 h-14",
					isSidebarOpen ? "px-6 gap-4" : "px-0 justify-center gap-0",
					$page.url.pathname === '/settings'
						? "bg-bg-tertiary text-text-primary border-l-white"
						: "text-text-secondary hover:bg-white/[0.03] hover:text-text-primary border-l-transparent"
				)}
				title={!isSidebarOpen ? "Settings" : ''}
			>
				<Settings size={18} class="shrink-0" />
				{#if isSidebarOpen}
					<span class="text-[12px] font-bold uppercase tracking-wider animate-in fade-in slide-in-from-left-2 duration-300">Settings</span>
				{/if}
			</a>

			<button
				class="flex h-12 items-center justify-center border-t border-border-color bg-bg-secondary text-text-secondary hover:text-text-primary transition-colors shrink-0"
				onclick={() => isSidebarOpen = !isSidebarOpen}
			>
				{#if isSidebarOpen}
					<ChevronLeft size={16} />
				{:else}
					<ChevronRight size={16} />
				{/if}
			</button>
		</div>
	</aside>

	<!-- MAIN CONTENT -->
	<main class="flex-1 min-w-0 flex flex-col relative overflow-hidden">
		<div class="flex-1 overflow-y-auto p-8 relative scrollbar-hide">
			{@render children()}
		</div>
	</main>
</div>

<style>
	:global(::-webkit-scrollbar) {
		width: 6px;
		height: 6px;
	}
	:global(::-webkit-scrollbar-track) {
		background: #0a0a0a;
	}
	:global(::-webkit-scrollbar-thumb) {
		background: #1a1a1a;
		border-radius: 4px;
	}
	:global(::-webkit-scrollbar-thumb:hover) {
		background: #2a2a2a;
	}
</style>
