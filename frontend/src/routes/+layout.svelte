<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import {
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
		{ name: 'Dashboard', href: '/', icon: LayoutDashboard },
		{ name: 'Index Browser', href: '/index-browser', icon: Library },
		{ name: 'File Tracking', href: '/tracking', icon: FolderTree },
		{ name: 'System Activity', href: '/jobs', icon: Activity },
		{ name: 'Physical Media', href: '/inventory', icon: CassetteTape },
		{ name: 'Restores', href: '/restores', icon: History }
	];

	let isSidebarOpen = $state(true);
</script>

<Toaster position="top-right" richColors />
<ScanStatusOverlay />

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
					<span class="truncate text-[12px] font-bold uppercase tracking-wider animate-in fade-in slide-in-from-left-2 duration-300">Settings</span>
				{/if}
			</a>

			<!-- COLLAPSE TOGGLE -->
			<button
				onclick={() => isSidebarOpen = !isSidebarOpen}
				class="h-10 w-full flex items-center justify-center hover:bg-white/5 text-text-secondary hover:text-text-primary transition-colors border-t border-border-color/50"
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
	<main class="flex-1 overflow-hidden relative flex flex-col min-w-0">
		<!-- Subtle background gradient -->
		<div class="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(59,130,246,0.03),transparent_50%)] pointer-events-none"></div>

		<div class="flex-1 overflow-y-auto p-8 relative z-10">
			<div class="max-w-[1600px] mx-auto h-full">
				{@render children()}
			</div>
		</div>
	</main>
</div>

<style>
	:global(body) {
		background-color: #000;
	}

	/* Custom scrollbar for brutalist look */
	:global(::-webkit-scrollbar) {
		width: 8px;
		height: 8px;
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
