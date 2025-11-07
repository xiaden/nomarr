// Analytics & Visualization Module
import { UIHelpers } from './ui.js';

export class AnalyticsManager {
    constructor(app) {
        this.app = app;
        this.charts = {};
    }
    
    setupAnalyticsUI() {
        // Co-occurrence search (optional - may not exist on all pages)
        const searchInput = document.getElementById('co-occurrence-tag') || document.getElementById('cooccurrence-tag');
        const searchBtn = document.getElementById('btn-search-co-occurrence');
        
        if (searchBtn && searchInput) {
            searchBtn.onclick = () => {
                const tag = searchInput.value.trim();
                if (tag) {
                    this.loadTagCoOccurrences(tag);
                }
            };
            
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    searchBtn.click();
                }
            });
        }
    }
    
    async loadLibraryOverview() {
        console.log('[Analytics] Loading library overview...');
        try {
            const response = await fetch('/web/api/library/stats', {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load library overview');
            }
            
            const data = await response.json();
            
            document.getElementById('lib-total-files').textContent = (data.total_files || 0).toLocaleString();
            document.getElementById('lib-total-artists').textContent = (data.unique_artists || 0).toLocaleString();
            document.getElementById('lib-total-albums').textContent = (data.unique_albums || 0).toLocaleString();
            
            const hours = Math.floor((data.total_duration_seconds || 0) / 3600);
            const minutes = Math.floor(((data.total_duration_seconds || 0) % 3600) / 60);
            document.getElementById('lib-total-duration').textContent = `${hours}h ${minutes}m`;
            
        } catch (error) {
            console.error('[Analytics] Overview error:', error);
            UIHelpers.showError('Failed to load library overview: ' + error.message);
        }
    }
    
    async loadTagFrequencies() {
        console.log('[Analytics] Loading tag frequencies...');
        try {
            const response = await fetch('/web/api/analytics/tag-frequencies?limit=20', {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load tag frequencies');
            }
            
            const data = await response.json();
            console.log('[Analytics] Tag frequencies:', data);
            
            // Destroy existing chart
            if (this.charts.tagFrequency) {
                this.charts.tagFrequency.destroy();
            }
            
            // data has structure: { tag_frequencies: [{tag_key, total_count, unique_values}] }
            const frequencies = data.tag_frequencies || [];
            
            // Create bar chart
            const ctx = document.getElementById('tag-frequency-chart').getContext('2d');
            this.charts.tagFrequency = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: frequencies.map(item => item.tag_key.replace('nom:', '')),
                    datasets: [{
                        label: 'Occurrences',
                        data: frequencies.map(item => item.total_count),
                        backgroundColor: 'rgba(54, 162, 235, 0.6)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0 }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Top 20 Most Common Tags'
                        }
                    }
                }
            });
            
        } catch (error) {
            console.error('[Analytics] Tag frequencies error:', error);
            UIHelpers.showMessage('Failed to load tag frequencies', 'error');
        }
    }
    
    async loadTagCoOccurrences(tag) {
        try {
            // Check if we're being called from the inline onclick or the proper UI
            const inputElement = document.getElementById('cooccurrence-tag');
            if (!tag && inputElement) {
                tag = inputElement.value.trim();
            }
            
            if (!tag) {
                UIHelpers.showMessage('Please enter a tag name', 'error');
                return;
            }
            
            const response = await fetch(`/web/api/analytics/tag-co-occurrences/${encodeURIComponent(tag)}?limit=10`, {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load co-occurrences');
            }
            
            const data = await response.json();
            
            // Update summary (if element exists)
            const summaryEl = document.getElementById('co-occurrence-summary');
            if (summaryEl) {
                summaryEl.innerHTML = `
                    <p><strong>Tag:</strong> ${UIHelpers.escapeHtml(tag)}</p>
                    <p><strong>Total occurrences:</strong> ${data.total_occurrences.toLocaleString()}</p>
                `;
            }
            
            // Show results container
            const resultsEl = document.getElementById('cooccurrence-results');
            if (resultsEl) {
                resultsEl.style.display = 'block';
            }
            
            // Render bar chart (if canvas exists)
            const chartCanvas = document.getElementById('chart-co-occurrence') || document.getElementById('cooccurrence-chart');
            if (chartCanvas) {
                if (this.charts.coOccurrence) {
                    this.charts.coOccurrence.destroy();
                }
                
                const ctx = chartCanvas.getContext('2d');
                this.charts.coOccurrence = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: data.co_occurrences.map(item => item.tag),
                        datasets: [{
                            label: 'Co-occurrence %',
                            data: data.co_occurrences.map(item => item.percentage),
                            backgroundColor: 'rgba(75, 192, 192, 0.6)',
                            borderColor: 'rgba(75, 192, 192, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            y: {
                                beginAtZero: true,
                                max: 100,
                                ticks: {
                                    callback: function(value) {
                                        return value + '%';
                                    }
                                }
                            }
                        },
                        plugins: {
                            legend: { display: false },
                            title: {
                                display: true,
                                text: `Tags that appear with "${tag}"`
                            }
                        }
                    }
                });
            }
            
            // Render top artists list (if element exists)
            const artistsEl = document.getElementById('co-occurrence-artists') || document.getElementById('cooccurrence-artists');
            if (artistsEl && data.top_artists) {
                this.renderTagList(artistsEl.id, data.top_artists);
            }
            
            // Render top genres list (if element exists)  
            const genresEl = document.getElementById('co-occurrence-genres') || document.getElementById('cooccurrence-genres');
            if (genresEl && data.top_genres) {
                this.renderTagList(genresEl.id, data.top_genres);
            }
            
        } catch (error) {
            console.error('[Analytics] Co-occurrences error:', error);
            UIHelpers.showMessage(`Failed to load co-occurrences: ${error.message}`, 'error');
        }
    }
    
    async loadMoodDistribution() {
        console.log('[Analytics] Loading mood distribution...');
        try {
            const response = await fetch('/web/api/analytics/mood-distribution', {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load mood distribution');
            }
            
            const data = await response.json();
            console.log('[Analytics] Mood distribution:', data);
            
            // Destroy existing chart
            if (this.charts.moodDistribution) {
                this.charts.moodDistribution.destroy();
            }
            
            // data has structure: { mood_distribution: [{mood, count, percentage}] }
            const moods = data.mood_distribution || [];
            
            // Generate colors
            const colors = this.generateColors(moods.length);
            
            // Create pie chart
            const ctx = document.getElementById('mood-chart').getContext('2d');
            this.charts.moodDistribution = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: moods.map(item => item.mood),
                    datasets: [{
                        data: moods.map(item => item.count),
                        backgroundColor: colors.background,
                        borderColor: colors.border,
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: { boxWidth: 15 }
                        },
                        title: {
                            display: true,
                            text: 'Mood Tags Distribution'
                        }
                    }
                }
            });
            
        } catch (error) {
            console.error('[Analytics] Mood distribution error:', error);
            UIHelpers.showError('Failed to load mood distribution: ' + error.message);
        }
    }
    
    async loadCorrelationMatrix() {
        console.log('[Analytics] Loading correlation matrix...');
        try {
            const response = await fetch('/web/api/analytics/tag-correlations?top_n=20', {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load correlation matrix');
            }
            
            const data = await response.json();
            console.log('[Analytics] Correlation data:', data);
            
            // Render VALUE-based correlations
            const container = document.getElementById('correlation-matrix');
            container.innerHTML = '';
            
            // New structure: { mood_correlations, mood_genre_correlations, mood_tier_correlations }
            const moodCorr = data.mood_correlations || {};
            const genreCorr = data.mood_genre_correlations || {};
            const tierCorr = data.mood_tier_correlations || {};
            
            if (Object.keys(moodCorr).length === 0) {
                container.innerHTML = '<p class="info-text">No correlation data available</p>';
                return;
            }
            
            // Section 1: Mood-to-Mood Correlations
            const moodSection = document.createElement('div');
            moodSection.innerHTML = '<h4>Mood Co-occurrences</h4>';
            const moodTable = this.createCorrelationTable(moodCorr, 'Mood');
            moodSection.appendChild(moodTable);
            container.appendChild(moodSection);
            
            // Section 2: Mood-to-Genre Correlations
            if (Object.keys(genreCorr).length > 0) {
                const genreSection = document.createElement('div');
                genreSection.style.marginTop = '30px';
                genreSection.innerHTML = '<h4>Mood-Genre Correlations</h4>';
                const genreTable = this.createCorrelationTable(genreCorr, 'Genre');
                genreSection.appendChild(genreTable);
                container.appendChild(genreSection);
            }
            
            // Section 3: Mood-to-Attribute Correlations
            if (Object.keys(tierCorr).length > 0) {
                const tierSection = document.createElement('div');
                tierSection.style.marginTop = '30px';
                tierSection.innerHTML = '<h4>Mood-Attribute Correlations</h4>';
                const tierTable = this.createCorrelationTable(tierCorr, 'Attribute');
                tierSection.appendChild(tierTable);
                container.appendChild(tierSection);
            }
            
        } catch (error) {
            console.error('[Analytics] Correlation matrix error:', error);
            UIHelpers.showError('Failed to load correlation matrix: ' + error.message);
        }
    }
    
    createCorrelationTable(correlations, type) {
        const table = document.createElement('table');
        table.className = 'correlation-table';
        table.style.width = '100%';
        table.style.fontSize = '0.85rem';
        
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        headerRow.innerHTML = `<th>Mood</th><th>Top ${type} Correlations</th>`;
        thead.appendChild(headerRow);
        table.appendChild(thead);
        
        const tbody = document.createElement('tbody');
        
        // Sort moods by total correlation strength (sum of all correlations)
        const sortedMoods = Object.entries(correlations).sort((a, b) => {
            const sumA = Object.values(a[1]).reduce((acc, val) => acc + val, 0);
            const sumB = Object.values(b[1]).reduce((acc, val) => acc + val, 0);
            return sumB - sumA;
        });
        
        sortedMoods.forEach(([mood, corrs]) => {
            const tr = document.createElement('tr');
            
            const moodCell = document.createElement('td');
            moodCell.textContent = mood;
            moodCell.style.fontWeight = 'bold';
            moodCell.style.width = '150px';
            tr.appendChild(moodCell);
            
            const corrsCell = document.createElement('td');
            
            // Create correlation badges
            const badges = Object.entries(corrs)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 5)  // Top 5 correlations
                .map(([name, value]) => {
                    const percentage = Math.round(value * 100);
                    const color = this.getCorrelationColorValue(value);
                    return `<span class="correlation-badge" style="background: ${color}; padding: 2px 8px; margin: 2px; border-radius: 4px; display: inline-block; font-size: 0.8rem;">${name} (${percentage}%)</span>`;
                })
                .join(' ');
            
            corrsCell.innerHTML = badges || '<em>No correlations</em>';
            tr.appendChild(corrsCell);
            
            tbody.appendChild(tr);
        });
        
        table.appendChild(tbody);
        return table;
    }
    
    getCorrelationColorValue(value) {
        // Color gradient from blue (low) to red (high)
        if (value >= 0.7) return '#ef4444';  // red
        if (value >= 0.5) return '#f59e0b';  // orange
        if (value >= 0.3) return '#fbbf24';  // yellow
        if (value >= 0.15) return '#60a5fa'; // light blue
        return '#93c5fd';  // very light blue
    }
    
    renderTagList(containerId, items) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        
        if (items.length === 0) {
            container.innerHTML = '<p>No data available</p>';
            return;
        }
        
        const list = document.createElement('div');
        list.className = 'tag-list';
        
        items.forEach(item => {
            const div = document.createElement('div');
            div.className = 'tag-list-item';
            div.innerHTML = `
                <span class="tag-name">${UIHelpers.escapeHtml(item.name)}</span>
                <span class="tag-count">${item.count} (${item.percentage.toFixed(1)}%)</span>
            `;
            list.appendChild(div);
        });
        
        container.appendChild(list);
    }
    
    generateColors(count) {
        const background = [];
        const border = [];
        
        for (let i = 0; i < count; i++) {
            const hue = (i * 360 / count) % 360;
            background.push(`hsla(${hue}, 70%, 60%, 0.6)`);
            border.push(`hsla(${hue}, 70%, 50%, 1)`);
        }
        
        return { background, border };
    }
    
    getCorrelationColor(value) {
        // Map 0-1 to blue-white-red gradient
        if (value < 0.5) {
            const intensity = Math.floor(value * 2 * 255);
            return `rgb(${255 - intensity}, ${255 - intensity}, 255)`;
        } else {
            const intensity = Math.floor((value - 0.5) * 2 * 255);
            return `rgb(255, ${255 - intensity}, ${255 - intensity})`;
        }
    }
}
