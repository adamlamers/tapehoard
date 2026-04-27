<script lang="ts">
        import {
                ChevronLeft,
                ChevronRight,
                ChevronUp,
                RotateCw,
                Search,
                Folder,
                ArrowUpDown,
                CheckSquare,
                Square
        } from "lucide-svelte";
        import { Button } from "$lib/components/ui/button";
        import { Checkbox } from "$lib/components/ui/checkbox";
        import { ScrollArea } from "$lib/components/ui/scroll-area";
        import { Input } from "$lib/components/ui/input";
        import FileBrowserTreeItem from "./FileBrowserTreeItem.svelte";
        import FileBrowserRowItem from "./FileBrowserRowItem.svelte";
        import type { FileItem, Breadcrumb } from "$lib/types";
        import { cn } from "$lib/utils";

        let {
                currentPath = $bindable("ROOT"),
                searchQuery = $bindable(""),
                files = [],
                onNavigate = (path: string) => {},
                onToggleTrack = (item: FileItem) => {},
                onSelect = (item: FileItem) => {},
                mode = "host",
                isSearching = false,
                pendingChanges = new Map<string, boolean>()
        } = $props<{
                currentPath?: string;
                searchQuery?: string;
                files?: FileItem[];
                onNavigate?: (path: string) => void;
                onToggleTrack?: (item: FileItem) => void;
                onSelect?: (item: FileItem) => void;
                mode?: "host" | "index" | "cart" | "live";
                isSearching?: boolean;
                pendingChanges?: Map<string, boolean>;
        }>();

        let selectedPaths = $state<Set<string>>(new Set());
        let lastSelectedPath = $state<string | null>(null);
        let sortColumn = $state<"name" | "size" | "mtime" | "type">("name");
        let sortDirection = $state<"asc" | "desc">("asc");

        // --- Navigation History ---
        let navigationHistory = $state<string[]>([currentPath]);
        let historyIndex = $state(0);
        let isInternalNavigation = false;

        // Effect to catch external path changes (Deep-Linking)
        $effect(() => {
                if (currentPath !== navigationHistory[historyIndex]) {
                        if (isInternalNavigation) {
                                // Handled by navigateTo helper
                                isInternalNavigation = false;
                        } else {
                                // External source updated currentPath (e.g. Query Param from Treemap)
                                // Jump directly and reset history to this point
                                navigationHistory = [currentPath];
                                historyIndex = 0;
                        }
                }
        });

        function navigateTo(path: string) {
                if (path !== currentPath) {
                        isInternalNavigation = true;
                        const newHistory = navigationHistory.slice(0, historyIndex + 1);
                        newHistory.push(path);
                        navigationHistory = newHistory;
                        historyIndex = navigationHistory.length - 1;
                        currentPath = path;
                }
                onNavigate(path);
        }

        function goBack() {
                if (historyIndex > 0) {
                        isInternalNavigation = true;
                        historyIndex--;
                        currentPath = navigationHistory[historyIndex];
                        onNavigate(currentPath);
                }
        }

        function goForward() {
                if (historyIndex < navigationHistory.length - 1) {
                        isInternalNavigation = true;
                        historyIndex++;
                        currentPath = navigationHistory[historyIndex];
                        onNavigate(currentPath);
                }
        }

        function goUp() {
                if (currentPath === "ROOT") return;
                const parts = currentPath.split("/");
                parts.pop();
                const parent = parts.join("/") || "ROOT";
                navigateTo(parent);
        }

        // --- Column Resizing Logic ---
        let mtimeWidth = $state(200);
        let typeWidth = $state(150);
        let sizeWidth = $state(120);

        let resizingCol = $state<string | null>(null);
        let startX = 0;
        let startWidth = 0;

        function startResize(e: MouseEvent, col: string) {
                e.preventDefault();
                resizingCol = col;
                startX = e.clientX;
                if (col === 'mtime') startWidth = mtimeWidth;
                else if (col === 'type') startWidth = typeWidth;
                else if (col === 'size') startWidth = sizeWidth;

                window.addEventListener('mousemove', handleMouseMove);
                window.addEventListener('mouseup', stopResize);
                document.body.style.cursor = 'col-resize';
        }

        function handleMouseMove(e: MouseEvent) {
                if (!resizingCol) return;
                const delta = e.clientX - startX;
                if (resizingCol === 'mtime') mtimeWidth = Math.max(100, startWidth + delta);
                else if (resizingCol === 'type') typeWidth = Math.max(80, startWidth + delta);
                else if (resizingCol === 'size') sizeWidth = Math.max(60, startWidth + delta);
        }

        function stopResize() {
                resizingCol = null;
                window.removeEventListener('mousemove', handleMouseMove);
                window.removeEventListener('mouseup', stopResize);
                document.body.style.cursor = '';
        }

        const colWidths = $derived({
                mtime: mtimeWidth,
                type: typeWidth,
                size: sizeWidth
        });

        // --- Navigation Tree Definition ---

        const sourceDataRoot = $derived({
                name: "All Sources",
                path: "ROOT",
                expanded: true,
                children: [],
                hasChildren: true
        });

        const virtualIndexRoot = $derived({
                name: "Archive Index",
                path: "ROOT",
                expanded: true,
                children: [],
                hasChildren: true
        });

        const recoveryQueueRoot = $derived({
                name: "Data Recovery",
                path: "ROOT",
                expanded: true,
                children: [],
                hasChildren: true
        });

        const activeRoot = $derived(
                mode === "host" ? sourceDataRoot :
                mode === "index" ? virtualIndexRoot :
                recoveryQueueRoot
        );

        // --- Logic ---

        const breadcrumbs = $derived.by(() => {
                if (currentPath === "ROOT") {
                    let name = "All Sources";
                    if (mode === "index") name = "Archive Index";
                    if (mode === "cart") name = "Data Recovery";
                    return [{ name, path: "ROOT" }];
                }

                const parts = currentPath.split("/").filter(Boolean);
                const crumbs: Breadcrumb[] = [];

                let rootName = "All Sources";
                if (mode === "index") rootName = "Archive Index";
                if (mode === "cart") rootName = "Data Recovery";
                crumbs.push({ name: rootName, path: "ROOT" });

                let current = "";
                for (const part of parts) {
                    current += `/${part}`;
                    crumbs.push({ name: part, path: current });
                }
                return crumbs;
        });

        const filteredFiles = $derived.by(() => {
                // When doing backend search, the parent feeds us already-filtered results.
                // We'll still do a light local filter to ensure things like name matching,
                // but we should match on the full path just in case.
                let result = files.filter((f: FileItem) => f.path.toLowerCase().includes((searchQuery || "").toLowerCase()));

                result.sort((a: FileItem, b: FileItem) => {
                        const valA = sortColumn === "type" ? a.type : a[sortColumn as keyof FileItem] || 0;
                        const valB = sortColumn === "type" ? b.type : b[sortColumn as keyof FileItem] || 0;

                        if (valA < (valB as any)) return sortDirection === "asc" ? -1 : 1;
                        if (valA > (valB as any)) return sortDirection === "asc" ? 1 : -1;
                        return 0;
                });

                return result;
        });

        function toggleSort(col: typeof sortColumn) {
                if (sortColumn === col) {
                        sortDirection = sortDirection === "asc" ? "desc" : "asc";
                } else {
                        sortColumn = col;
                        sortDirection = "asc";
                }
        }

        function handleRowClick(e: MouseEvent, item: FileItem) {
                if (e.shiftKey && lastSelectedPath) {
                        const lastIndex = filteredFiles.findIndex((f: FileItem) => f.path === lastSelectedPath);
                        const currentIndex = filteredFiles.findIndex((f: FileItem) => f.path === item.path);
                        const start = Math.min(lastIndex, currentIndex);
                        const end = Math.max(lastIndex, currentIndex);

                        const newSelection = new Set(selectedPaths);
                        for (let i = start; i <= end; i++) {
                                newSelection.add(filteredFiles[i].path);
                        }
                        selectedPaths = newSelection;
                } else if (e.metaKey || e.ctrlKey) {
                        const newSelection = new Set(selectedPaths);
                        if (newSelection.has(item.path)) {
                                newSelection.delete(item.path);
                        } else {
                                newSelection.add(item.path);
                        }
                        selectedPaths = newSelection;
                        lastSelectedPath = item.path;
                } else {
                        selectedPaths = new Set([item.path]);
                        lastSelectedPath = item.path;
                }

                // Signal selection to parent
                onSelect(item);
        }

        function handleRowDoubleClick(item: FileItem) {
                if (item.type === "directory") {
                        navigateTo(item.path);
                        selectedPaths = new Set();
                        lastSelectedPath = null;
                }
        }

        function handleSelectAll(checked: boolean | "indeterminate") {
                if (checked === true) {
                        selectedPaths = new Set(filteredFiles.map((f: FileItem) => f.path));
                } else {
                        selectedPaths = new Set();
                }
        }

        let isEditingPath = $state(false);
        let pathInputValue = $state("");

        function handleAddressClick() {
                pathInputValue = currentPath;
                isEditingPath = true;
        }

        function handlePathSubmit() {
                navigateTo(pathInputValue);
                isEditingPath = false;
        }

        function handleKeyDown(e: KeyboardEvent) {
                if (isEditingPath) {
                        if (e.key === "Enter") handlePathSubmit();
                        if (e.key === "Escape") isEditingPath = false;
                        return;
                }

                if (e.key === "Enter" && selectedPaths.size === 1) {
                        const item = files.find((f: FileItem) => f.path === Array.from(selectedPaths)[0]);
                        if (item && item.type === "directory") {
                                handleRowDoubleClick(item);
                        }
                }
                if (e.key === "Backspace") {
                        // Don't navigate back if user is typing in an input
                        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
                                return;
                        }

                        if (currentPath === "ROOT") return;
                        const parts = currentPath.split("/").filter(Boolean);
                        if (parts.length === 1) {
                                onNavigate("ROOT");
                        } else {
                                onNavigate("/" + parts.slice(0, -1).join("/"));
                        }
                }
                if ((e.ctrlKey || e.metaKey) && e.key === "f") {
                        e.preventDefault();
                        const searchInput = document.getElementById("browser-search") as HTMLInputElement;
                        searchInput?.focus();
                }
        }
</script>

<div
        class="file-browser flex h-full flex-col overflow-hidden rounded-lg border border-border-color bg-bg-secondary shadow-2xl min-w-0"
        onkeydown={handleKeyDown}
        tabindex="0"
        role="application"
        aria-label="File Browser"
>
        <!-- ZONE A: TOP BAR -->
        <div class="flex h-14 shrink-0 items-center justify-between border-b border-border-color bg-bg-tertiary/50 px-6 shadow-sm">
                <div class="flex items-center gap-4 flex-1 min-w-0">
                        <!-- Navigation Buttons -->
                        <div class="flex items-center gap-1 shrink-0">
                                <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5"
                                        onclick={goBack}
                                        disabled={historyIndex <= 0}
                                >
                                        <ChevronLeft size={18}></ChevronLeft>
                                </Button>
                                <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5"
                                        onclick={goForward}
                                        disabled={historyIndex >= navigationHistory.length - 1}
                                >
                                        <ChevronRight size={18}></ChevronRight>
                                </Button>
                                <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5"
                                        onclick={() => {
                                                if (currentPath === "ROOT") return;
                                                const parts = currentPath.split("/").filter(Boolean);
                                                if (parts.length === 1) {
                                                    onNavigate("ROOT");
                                                } else {
                                                    onNavigate("/" + parts.slice(0, -1).join("/"));
                                                }
                                        }}
                                >
                                        <ChevronUp size={18}></ChevronUp>
                                </Button>
                        </div>

                        <!-- Address Bar -->
                        <div
                                class="flex-1 flex items-center bg-bg-primary border border-border-color/40 rounded-md px-3 h-9 shadow-inner overflow-hidden max-w-3xl group transition-all focus-within:border-action-color/50 min-w-0"
                                onclick={handleAddressClick}
                                role="button"
                                tabindex="-1"
                        >
                                <Folder size={16} class="text-yellow-500/80 mr-2 shrink-0"></Folder>

                                {#if isEditingPath}
                                        <input
                                                type="text"
                                                class="flex-1 bg-transparent border-none outline-none text-[13px] text-text-primary mono"
                                                bind:value={pathInputValue}
                                                onblur={() => setTimeout(() => isEditingPath = false, 100)}
                                                autoFocus
                                        />
                                {:else}
                                        <div class="flex-1 flex items-center overflow-x-auto scrollbar-hide">
                                                {#each breadcrumbs as crumb, i}
                                                        {#if i > 0}
                                                                <ChevronRight size={14} class="mx-1 text-text-secondary/30 shrink-0"></ChevronRight>
                                                        {/if}
                                                        <button
                                                                class={cn(
                                                                        "px-2 py-0.5 rounded-md text-[13px] transition-colors hover:bg-white/5 whitespace-nowrap cursor-pointer",
                                                                        i === breadcrumbs.length - 1 ? "text-text-primary font-bold" : "text-text-secondary hover:text-text-primary"
                                                                )}
                                                                onclick={(e) => { e.stopPropagation(); navigateTo(crumb.path); }}
                                                        >
                                                                {crumb.name}
                                                        </button>
                                                {/each}
                                        </div>
                                {/if}

                                <button class="ml-2 text-text-secondary hover:text-text-primary p-1 transition-colors cursor-pointer shrink-0" onclick={(e) => { e.stopPropagation(); navigateTo(currentPath); }}>
                                        <RotateCw size={14}></RotateCw>
                                </button>
                        </div>
                </div>

                <!-- Search Input -->
                <div class="flex items-center shrink-0 ml-12">
                        <div class="relative w-48 sm:w-64 group">
                                {#if isSearching}
                                        <RotateCw size={14} class="absolute left-3 top-3 text-action-color animate-spin"></RotateCw>
                                {:else}
                                        <Search
                                                size={14}
                                                class="absolute left-3 top-3 text-text-secondary group-focus-within:text-action-color transition-colors"
                                        ></Search>
                                {/if}
                                <Input
                                        id="browser-search"
                                        type="text"
                                        placeholder="Search folder"
                                        bind:value={searchQuery}
                                        class="h-9 bg-bg-primary/50 pl-10 text-[13px] placeholder:text-text-secondary/50 border-border-color/40 focus-visible:ring-action-color/40 transition-all rounded-md"
                                />
                        </div>
                </div>
        </div>

        <div class="flex flex-1 overflow-hidden">
                <!-- ZONE B: NAVIGATION PANE -->
                <aside class="flex w-72 shrink-0 flex-col border-r border-border-color bg-bg-secondary/50">
                        <ScrollArea class="flex-1 p-2">
                                <div class="px-3 py-1 text-[11px] font-bold uppercase text-text-secondary/60 mb-2">
                                        Navigation
                                </div>
                                <FileBrowserTreeItem node={activeRoot} selectedPath={currentPath} onSelect={navigateTo} isSpecial={true} {mode} />
                        </ScrollArea>
                </aside>

                <!-- ZONE C: DETAILS PANE -->
                <div class="flex min-w-0 flex-1 flex-col bg-bg-primary shadow-inner overflow-hidden">
                        <div class="flex flex-col flex-1 min-w-0 overflow-x-auto scrollbar-hide">
                                <div class="min-w-max flex flex-col flex-1">
                                        <!-- Column Headers -->
                                        <div class="flex h-10 items-center border-b border-border-color bg-bg-tertiary/30 shrink-0 select-none border-l-2 border-l-transparent">
                                                <div class="flex w-12 shrink-0 justify-center">
                                                        <Checkbox
                                                                checked={selectedPaths.size === filteredFiles.length && filteredFiles.length > 0}
                                                                onCheckedChange={handleSelectAll}
                                                        />
                                                </div>

                                                <div class="flex flex-auto min-w-[300px] items-center h-full relative group/col">
                                                        <button
                                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors"
                                                                onclick={() => toggleSort("name")}
                                                        >
                                                                Name
                                                                {#if sortColumn === "name"}
                                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                                {/if}
                                                        </button>
                                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                                        <div
                                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                                role="none"
                                                        ></div>
                                                </div>

                                                <div class="flex items-center h-full relative group/col shrink-0" style="width: {mtimeWidth}px">
                                                        <button
                                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors"
                                                                onclick={() => toggleSort("mtime")}
                                                        >
                                                                Date modified
                                                                {#if sortColumn === "mtime"}
                                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                                {/if}
                                                        </button>
                                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                                        <div
                                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                                onmousedown={(e) => startResize(e, 'mtime')}
                                                                role="none"
                                                        ></div>
                                                </div>

                                                <div class="flex items-center h-full relative group/col shrink-0" style="width: {typeWidth}px">
                                                        <button
                                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors"
                                                                onclick={() => toggleSort("type")}
                                                        >
                                                                Type
                                                                {#if sortColumn === "type"}
                                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                                {/if}
                                                        </button>
                                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                                        <div
                                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                                onmousedown={(e) => startResize(e, 'type')}
                                                                role="none"
                                                        ></div>
                                                </div>

                                                <div class="flex items-center h-full relative group/col shrink-0" style="width: {sizeWidth}px">
                                                        <button
                                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors text-right"
                                                                onclick={() => toggleSort("size")}
                                                        >
                                                                Size
                                                                {#if sortColumn === "size"}
                                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                                {/if}
                                                        </button>
                                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                                        <div
                                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                                onmousedown={(e) => startResize(e, 'size')}
                                                                role="none"
                                                        ></div>
                                                </div>

                                                <div class="w-10 shrink-0"></div>
                                        </div>

                                        <!-- Scrollable File List -->
                                        <div class="flex-1 overflow-y-auto min-h-0">
                                                {#if filteredFiles.length === 0}
                                                        <div class="flex h-full flex-col items-center justify-center p-12 text-center opacity-30">
                                                                <Search size={48} class="mb-4" strokeWidth={1}></Search>
                                                                <p class="text-sm font-medium uppercase tracking-widest">Folder is empty</p>
                                                        </div>
                                                {:else}
                                                        {#each filteredFiles as item (item.path)}
                                                                <FileBrowserRowItem
                                                                        {item}
                                                                        {mode}
                                                                        {colWidths}
                                                                        isSelected={selectedPaths.has(item.path)}
                                                                        isStaged={pendingChanges.has(item.path)}
                                                                        onClick={(e) => handleRowClick(e, item)}
                                                                        onDoubleClick={() => handleRowDoubleClick(item)}
                                                                        onToggleTrack={() => onToggleTrack(item)}
                                                                />
                                                        {/each}
                                                {/if}
                                        </div>
                                </div>
                        </div>
                </div>
        </div>

        <!-- ZONE D: STATUS BAR -->
        <div
                class="flex h-8 shrink-0 items-center justify-between border-t border-border-color bg-bg-tertiary px-6 text-[10px] font-medium text-text-secondary"
        >
                <div class="flex items-center gap-4">
                        <span>{filteredFiles.length} items</span>
                        <div class="h-3 w-px bg-border-color/40"></div>
                        {#if selectedPaths.size > 0}
                                <span class="text-text-primary">
                                        {selectedPaths.size} items selected
                                </span>
                        {/if}
                </div>
                <div class="flex items-center gap-3">
                </div>
        </div>
</div>

<style>
        :global(.scrollbar-hide::-webkit-scrollbar) {
                display: none;
        }
        :global(.scrollbar-hide) {
                -ms-overflow-style: none;
                scrollbar-width: none;
        }
</style>
