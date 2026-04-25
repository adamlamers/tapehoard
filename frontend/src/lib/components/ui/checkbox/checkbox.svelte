<script lang="ts">
	import { Checkbox as CheckboxPrimitive } from "bits-ui";
	import { Check, Minus } from "lucide-svelte";
	import { cn } from "$lib/utils";

	let {
	        class: className,
	        checked = $bindable(false),
	        indeterminate = false,
	        ...rest
	}: any = $props();</script>

	<CheckboxPrimitive.Root
	bind:checked
	class={cn(
	        "peer h-4 w-4 shrink-0 rounded-sm border border-border-color bg-bg-primary ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action-color focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-action-color data-[state=checked]:border-action-color data-[state=checked]:text-white data-[state=indeterminate]:bg-action-color data-[state=indeterminate]:border-action-color data-[state=indeterminate]:text-white transition-all",
	        className
	)}
	{...rest}
	>
	{#if checked === true}
	        <div class="flex items-center justify-center text-current h-full w-full animate-in zoom-in-50 duration-200">
	                <Check class="h-3.5 w-3.5 stroke-[3]" />
	        </div>
	{:else if indeterminate || checked === "indeterminate"}
	        <div class="flex items-center justify-center text-current h-full w-full animate-in zoom-in-50 duration-200">
	                <Minus class="h-3.5 w-3.5 stroke-[4]" />
	        </div>
	{/if}
	</CheckboxPrimitive.Root>
