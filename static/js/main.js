// Конфигурация API
const API_BASE = '/api';

function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split('; ') : [];
    for (const cookie of cookies) {
        const [cookieName, ...rest] = cookie.split('=');
        if (cookieName === name) {
            return decodeURIComponent(rest.join('='));
        }
    }
    return '';
}

function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || getCookie('csrftoken') || '';
}

// Утилиты для работы с API
async function apiCall(method, endpoint, data = null) {
    const csrfToken = getCsrfToken();
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        }
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        const responseText = await response.text();

        let payload = null;
        if (responseText) {
            try {
                payload = JSON.parse(responseText);
            } catch {
                payload = responseText;
            }
        }

        if (!response.ok) {
            const errorMessage = (payload && (payload.error || payload.detail || payload.message))
                || (typeof payload === 'string' && payload)
                || `HTTP Error: ${response.status}`;
            throw new Error(errorMessage);
        }

        if (response.status === 204 || !responseText) {
            return null;
        }

        return payload;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

function unwrapListResponse(data) {
    if (Array.isArray(data)) {
        return data;
    }
    if (data && Array.isArray(data.results)) {
        return data.results;
    }
    return [];
}

// Функции для работы с комнатами
async function getRooms() {
    try {
        const data = await apiCall('GET', '/rooms/');
        return unwrapListResponse(data);
    } catch (error) {
        console.error('Ошибка при загрузке комнат:', error);
        return [];
    }
}

async function createRoom(name, description) {
    try {
        return await apiCall('POST', '/rooms/', { name, description });
    } catch (error) {
        console.error('Ошибка при создании комнаты:', error);
        throw error;
    }
}

async function joinRoomRequest(code) {
    try {
        return await apiCall('POST', '/rooms/join_room/', { code });
    } catch (error) {
        console.error('Ошибка при присоединении к комнате:', error);
        throw error;
    }
}

async function getRoomStats(roomId) {
    try {
        return await apiCall('GET', `/rooms/${roomId}/statistics/`);
    } catch (error) {
        console.error('Ошибка при загрузке статистики:', error);
        return null;
    }
}

async function getRoomManualLoans(roomId) {
    try {
        const data = await apiCall('GET', `/loans/?room=${roomId}`);
        return unwrapListResponse(data);
    } catch (error) {
        console.error('Ошибка при загрузке ручных долгов:', error);
        return [];
    }
}

// Функции для работы с задачами
async function getTasks(roomId = null) {
    try {
        let endpoint = '/tasks/';
        if (roomId) {
            endpoint += `?room=${roomId}`;
        }
        const data = await apiCall('GET', endpoint);
        return unwrapListResponse(data);
    } catch (error) {
        console.error('Ошибка при загрузке задач:', error);
        return [];
    }
}

async function createTask(roomId, title, description, assignedToId = null, priority = 'medium') {
    try {
        return await apiCall('POST', '/tasks/', {
            room: roomId,
            title,
            description,
            assigned_to_id: assignedToId,
            priority,
            status: 'pending'
        });
    } catch (error) {
        console.error('Ошибка при создании задачи:', error);
        throw error;
    }
}

async function updateTask(taskId, data) {
    try {
        return await apiCall('PATCH', `/tasks/${taskId}/`, data);
    } catch (error) {
        console.error('Ошибка при обновлении задачи:', error);
        throw error;
    }
}

async function completeTask(taskId) {
    try {
        return await apiCall('POST', `/tasks/${taskId}/complete/`);
    } catch (error) {
        console.error('Ошибка при завершении задачи:', error);
        throw error;
    }
}

// Функции для работы с расходами
async function getExpenses(roomId = null) {
    try {
        let endpoint = '/expenses/';
        if (roomId) {
            endpoint += `?room=${roomId}`;
        }
        const data = await apiCall('GET', endpoint);
        return unwrapListResponse(data);
    } catch (error) {
        console.error('Ошибка при загрузке расходов:', error);
        return [];
    }
}

async function createExpense(roomId, description, amount, paidById, category, shares, sharedWithRoom = false, markAsPaid = false) {
    try {
        return await apiCall('POST', '/expenses/', {
            room: roomId,
            description,
            amount,
            paid_by_id: paidById,
            category,
            shares,
            shared_with_room: sharedWithRoom,
            mark_as_paid: markAsPaid
        });
    } catch (error) {
        console.error('Ошибка при создании расхода:', error);
        throw error;
    }
}

async function updateExpense(expenseId, data) {
    try {
        return await apiCall('PATCH', `/expenses/${expenseId}/`, data);
    } catch (error) {
        console.error('Ошибка при обновлении расхода:', error);
        throw error;
    }
}

// Функции для работы с долями расходов
async function settleExpenseShare(shareId) {
    try {
        return await apiCall('POST', `/expense-shares/${shareId}/settle/`);
    } catch (error) {
        console.error('Ошибка при отметке доли:', error);
        throw error;
    }
}

// Функции для работы с участниками
async function getRoomMembers(roomId) {
    try {
        const data = await apiCall('GET', `/rooms/${roomId}/`);
        return data.members || [];
    } catch (error) {
        console.error('Ошибка при загрузке участников:', error);
        return [];
    }
}

// Функция для форматирования даты
function formatDate(dateString) {
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) {
        return 'Без срока';
    }
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    if (date.toDateString() === today.toDateString()) {
        return `сегодня, ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
    } else if (date.toDateString() === tomorrow.toDateString()) {
        return `завтра, ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
    } else {
        const days = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
        return `${days[date.getDay()]}, ${date.getDate()} ${getMonthName(date.getMonth())}`;
    }
}

function getMonthName(monthIndex) {
    const months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
    return months[monthIndex];
}

// Функции для отображения на странице
function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 16px 20px;
        background: ${type === 'success' ? '#2ecc71' : '#e74c3c'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;

    document.body.appendChild(notification);
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Обработчик для вступления в комнату
async function joinRoom(code) {
    if (!code || code.trim() === '') {
        showNotification('Пожалуйста, введите код комнаты', 'error');
        return;
    }

    try {
        const result = await apiCall('POST', '/rooms/join_room/', { code: code.trim() });
        showNotification(`Вы присоединились к комнате: ${result.name}`, 'success');
        // Перенаправить на панель управления
        setTimeout(() => {
            window.location.href = '/dashboard/';
        }, 1500);
    } catch (error) {
        showNotification('Неправильный код комнаты или ошибка сервера', 'error');
    }
}

// Обработчик для регистрации
async function handleRegister(event) {
    event.preventDefault();
    const fullName = document.getElementById('full-name')?.value;
    const email = document.getElementById('email')?.value;
    const password = document.getElementById('password')?.value;
    const passwordConfirm = document.getElementById('password-confirm')?.value;

    if (password !== passwordConfirm) {
        showNotification('Пароли не совпадают', 'error');
        return;
    }

    // TODO: Интегрировать с API регистрации
    showNotification('Функция регистрации еще не реализована', 'error');
}

// Функция для копирования кода комнаты
async function copyRoomCode() {
    try {
        // TODO: Получить реальный код из API
        const code = 'ABC123';
        await navigator.clipboard.writeText(code);
        showNotification(`Код скопирован: ${code}`, 'success');
    } catch (error) {
        showNotification('Ошибка при копировании', 'error');
    }
}

// Подсказка для аналитики
function initAnalytics() {
    console.log('COHUB v1.0 - Система управления совместной жизнью');
}

const THEME_STORAGE_KEY = 'cohub-theme';

function getSavedTheme() {
    try {
        return localStorage.getItem(THEME_STORAGE_KEY);
    } catch {
        return null;
    }
}

function saveTheme(theme) {
    try {
        localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
        // Если хранилище недоступно, продолжаем без сохранения
    }
}

function resolveInitialTheme() {
    const savedTheme = getSavedTheme();
    if (savedTheme === 'dark' || savedTheme === 'light') {
        return savedTheme;
    }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    // Синхронизируем тёмную тему Tabler/Bootstrap (компоненты читают data-bs-theme).
    document.documentElement.setAttribute('data-bs-theme', theme);

    const toggleBtn = document.getElementById('theme-toggle');
    if (!toggleBtn) {
        return;
    }

    const isDark = theme === 'dark';
    const labelEl = toggleBtn.querySelector('.theme-toggle__label');
    toggleBtn.setAttribute('aria-pressed', String(isDark));
    toggleBtn.setAttribute('title', isDark ? 'Переключить на светлый режим' : 'Переключить на тёмный режим');
    if (labelEl) {
        labelEl.textContent = isDark ? 'Светлый режим' : 'Тёмный режим';
    }
}

function initThemeToggle() {
    const initialTheme = resolveInitialTheme();
    applyTheme(initialTheme);

    const toggleBtn = document.getElementById('theme-toggle');
    if (!toggleBtn) {
        return;
    }

    toggleBtn.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
        const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
        applyTheme(nextTheme);
        saveTheme(nextTheme);
    });
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function () {
    initThemeToggle();
    initAnalytics();
    initOnboarding();
});

// Онбординг
function initOnboarding() {
    const modal = document.getElementById('onboarding-modal');
    if (!modal) return;

    const closeBtn = modal.querySelector('.close');
    const steps = modal.querySelectorAll('.onboarding-step');
    let currentStep = 0;

    // Показать онбординг, если не показан ранее
    if (!localStorage.getItem('onboardingShown')) {
        modal.style.display = 'block';
        showStep(currentStep);
    }

    // Закрыть модальное окно
    closeBtn.onclick = function () {
        modal.style.display = 'none';
        localStorage.setItem('onboardingShown', 'true');
    }

    // Кнопки шагов
    const nextButtons = modal.querySelectorAll('[id^="next-step-"]');
    nextButtons.forEach(btn => {
        btn.onclick = () => nextStep();
    });

    document.getElementById('finish-onboarding').onclick = () => {
        modal.style.display = 'none';
        localStorage.setItem('onboardingShown', 'true');
    }

    // Кнопка помощи
    const helpBtn = document.getElementById('help-button');
    if (helpBtn) {
        helpBtn.onclick = () => {
            modal.style.display = 'block';
            currentStep = 0;
            showStep(currentStep);
        }
    }

    function showStep(step) {
        steps.forEach((s, i) => {
            s.classList.toggle('active', i === step);
        });
    }

    function nextStep() {
        if (currentStep < steps.length - 1) {
            currentStep++;
            showStep(currentStep);
        }
    }
}
