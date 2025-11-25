import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Initialize Flask
app = Flask(__name__)
CORS(app)

# Configuration
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_API_TOKEN")
TRELLO_BOARD_ID = os.getenv("TRELLO_BOARD_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# ============================================
# TRELLO API FUNCTIONS
# ============================================

def get_trello_cards():
    """Fetch all cards from Trello board with detailed information"""
    try:
        url = f"https://api.trello.com/1/boards/{TRELLO_BOARD_ID}/cards"
        params = {
            'key': TRELLO_API_KEY,
            'token': TRELLO_TOKEN,
            'checklists': 'all',
            'actions': 'commentCard,updateCard',
            'fields': 'all'
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching Trello cards: {e}")
        return []

def get_trello_lists():
    """Fetch all lists from Trello board"""
    try:
        url = f"https://api.trello.com/1/boards/{TRELLO_BOARD_ID}/lists"
        params = {
            'key': TRELLO_API_KEY,
            'token': TRELLO_TOKEN
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching Trello lists: {e}")
        return []

def get_trello_labels():
    """Fetch all labels from Trello board"""
    try:
        url = f"https://api.trello.com/1/boards/{TRELLO_BOARD_ID}/labels"
        params = {
            'key': TRELLO_API_KEY,
            'token': TRELLO_TOKEN
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching labels: {e}")
        return []

def get_card_details(card_id):
    """Fetch detailed card information including activity"""
    try:
        url = f"https://api.trello.com/1/cards/{card_id}"
        params = {
            'key': TRELLO_API_KEY,
            'token': TRELLO_TOKEN,
            'checklists': 'all',
            'actions': 'all',
            'fields': 'all'
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching card details: {e}")
        return None

def normalize_tasks(trello_cards, trello_lists):
    """Convert Trello cards to normalized task format with enhanced data"""
    list_map = {l['id']: l['name'] for l in trello_lists}
    
    normalized = []
    for card in trello_cards:
        # Calculate completion percentage from checklists
        checklists = card.get('checklists', [])
        total_items = 0
        completed_items = 0
        
        for checklist in checklists:
            check_items = checklist.get('checkItems', [])
            total_items += len(check_items)
            completed_items += sum(1 for item in check_items if item.get('state') == 'complete')
        
        completion_pct = (completed_items / total_items * 100) if total_items > 0 else 0
        
        # Count comments and activities
        actions = card.get('actions', [])
        comment_count = sum(1 for action in actions if action.get('type') == 'commentCard')
        
        task = {
            'id': card['id'],
            'title': card['name'],
            'description': card.get('desc', ''),
            'source': 'trello',
            'status': list_map.get(card['idList'], 'unknown'),
            'assignee': card.get('idMembers', []),
            'deadline': card.get('due', None),
            'url': card.get('url', ''),
            'labels': [l['name'] for l in card.get('labels', [])],
            'idList': card.get('idList'),
            'dateLastActivity': card.get('dateLastActivity'),
            'checkItems': checklists,
            'total_checklist_items': total_items,
            'completed_checklist_items': completed_items,
            'completion_pct': round(completion_pct, 1),
            'comment_count': comment_count,
            'activity_count': len(actions)
        }
        normalized.append(task)
    
    return normalized

# ============================================
# ENHANCED PRIORITY CALCULATION ENGINE
# ============================================

def calculate_urgency(task):
    """
    Calculate deadline urgency score (0-100)
    Considers both deadlines and overdue status
    """
    deadline = task.get('deadline')
    if not deadline:
        return 15  # Low urgency for tasks without deadlines
    
    try:
        deadline_date = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
        now = datetime.now(deadline_date.tzinfo)
        hours_until = (deadline_date - now).total_seconds() / 3600
        days_until = hours_until / 24
        
        if hours_until < 0:
            # Overdue - scale based on how overdue
            days_overdue = abs(days_until)
            if days_overdue > 7:
                return 100  # Severely overdue
            elif days_overdue > 3:
                return 95
            else:
                return 90
        elif hours_until < 6:
            return 95  # Due within 6 hours
        elif hours_until < 24:
            return 85  # Due today
        elif days_until <= 2:
            return 75  # Due within 2 days
        elif days_until <= 4:
            return 60  # Due within 4 days
        elif days_until <= 7:
            return 45  # Due this week
        elif days_until <= 14:
            return 30  # Due in 2 weeks
        else:
            return 20  # Due later
    except Exception as e:
        print(f"Error calculating urgency: {e}")
        return 25

def calculate_strategic_value(task):
    """
    Calculate strategic alignment score (0-100)
    Considers labels, keywords, and business impact
    """
    labels = [l.lower() for l in task.get('labels', [])]
    title = task.get('title', '').lower()
    description = task.get('description', '').lower()
    
    # Critical/Emergency labels
    if any(label in labels for label in ['critical', 'blocker', 'emergency', 'urgent']):
        return 95
    
    # High priority labels
    if any(label in labels for label in ['high', 'important', 'high priority']):
        return 80
    
    # Bug/Fix indicators
    if any(keyword in title or keyword in description for keyword in ['bug', 'error', 'crash', 'broken', 'fix']):
        return 75
    
    # User-facing/Revenue impact
    if any(keyword in title or keyword in description for keyword in ['user-facing', 'revenue', 'customer', 'production']):
        return 70
    
    # Security/Compliance
    if any(keyword in title or keyword in description for keyword in ['security', 'vulnerability', 'compliance', 'audit']):
        return 85
    
    # Low priority indicators
    if any(label in labels for label in ['low', 'nice to have', 'enhancement', 'future']):
        return 25
    
    # Default medium priority
    return 50

def calculate_dependency_score(task, all_tasks):
    """
    Calculate dependency impact score (0-100)
    Checks both if this task blocks others and is blocked by others
    """
    score = 20  # Base score
    
    desc = task.get('description', '').lower()
    title = task.get('title', '').lower()
    task_id = task['id']
    
    # Check if THIS task is a blocker
    if 'blocker' in desc or 'blocking' in title or 'blocks' in desc:
        score += 50
    
    # Check how many other tasks reference this one (are blocked by it)
    blocked_count = 0
    for other_task in all_tasks:
        if other_task['id'] != task_id:
            other_desc = other_task.get('description', '').lower()
            other_title = other_task.get('title', '').lower()
            # Check if this task ID or title is mentioned
            if task_id in other_desc or title[:20] in other_desc or title[:20] in other_title:
                blocked_count += 1
    
    # Add points for each task that depends on this one
    score += min(blocked_count * 20, 40)  # Cap at 40 points
    
    # Check if this task is blocked by others
    if 'blocked by' in desc or 'waiting for' in desc or 'depends on' in desc:
        score -= 30  # Reduce priority if blocked
    
    return min(max(score, 0), 100)

def calculate_effort_impact(task):
    """
    Calculate effort vs impact score (0-100)
    High score = low effort, high impact (quick wins)
    """
    title = task.get('title', '').lower()
    desc = task.get('description', '').lower()
    checklist_items = task.get('total_checklist_items', 0)
    
    # Quick wins - low effort tasks
    quick_win_keywords = ['typo', 'rename', 'update text', 'copy change', 'wording', 
                          'small fix', 'quick', 'simple', 'minor']
    if any(keyword in title or keyword in desc for keyword in quick_win_keywords):
        return 90  # Do these first!
    
    # High effort indicators
    complex_keywords = ['refactor', 'rebuild', 'redesign', 'architecture', 
                       'migration', 'infrastructure', 'integration']
    if any(keyword in title or keyword in desc for keyword in complex_keywords):
        return 35  # Complex tasks - may need breaking down
    
    # Check subtasks/checklist complexity
    if checklist_items > 10:
        return 30  # Very complex
    elif checklist_items > 5:
        return 45  # Moderately complex
    elif checklist_items > 0:
        return 65  # Some complexity but manageable
    
    # Check description length as complexity indicator
    desc_length = len(desc)
    if desc_length > 1000:
        return 40  # Very detailed = complex
    elif desc_length > 500:
        return 55  # Detailed
    elif desc_length > 100:
        return 70  # Moderate detail
    elif desc_length > 0:
        return 75  # Brief
    else:
        return 60  # No description - unclear effort
    
    return 60  # Default

def calculate_staleness(task):
    """
    Calculate staleness penalty score (0-100)
    High score = task is stagnant and needs attention
    """
    status = task.get('status', '')
    last_activity = task.get('dateLastActivity')
    
    # Only penalize in-progress or in-review tasks
    if status not in ['In Progress', 'In Review', 'Testing']:
        return 20  # Not applicable
    
    if not last_activity:
        return 50  # No activity date, moderate concern
    
    try:
        last_date = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
        now = datetime.now(last_date.tzinfo)
        days_stale = (now - last_date).days
        
        if days_stale > 14:
            return 95  # Severely stagnant - critical attention needed
        elif days_stale > 7:
            return 85  # Very stale - needs immediate attention
        elif days_stale > 4:
            return 70  # Getting stale
        elif days_stale > 2:
            return 50  # Slightly stale
        else:
            return 25  # Fresh, actively worked on
    except Exception as e:
        print(f"Error calculating staleness: {e}")
        return 40
    
    return 30

def calculate_team_capacity(task):
    """
    Calculate team capacity score (0-100)
    Higher score = better team capacity to complete task
    """
    assignees = task.get('assignee', [])
    num_assignees = len(assignees)
    
    if num_assignees == 0:
        return 40  # Unassigned - needs assignment
    elif num_assignees == 1:
        return 75  # Single owner - clear accountability
    elif num_assignees == 2:
        return 85  # Paired - good collaboration
    elif num_assignees >= 3:
        return 70  # Many assignees - may have coordination overhead
    
    return 60

def calculate_activity_engagement(task):
    """
    Calculate engagement score based on comments and activity (0-100)
    High activity = high stakeholder interest
    """
    comment_count = task.get('comment_count', 0)
    activity_count = task.get('activity_count', 0)
    
    if comment_count > 10 or activity_count > 20:
        return 80  # High engagement
    elif comment_count > 5 or activity_count > 10:
        return 65  # Moderate engagement
    elif comment_count > 2 or activity_count > 5:
        return 50  # Some engagement
    elif comment_count > 0 or activity_count > 0:
        return 40  # Low engagement
    else:
        return 30  # No engagement

def calculate_priority_score(task, all_tasks):
    """
    Enhanced priority calculation with multiple factors
    
    Formula:
    Priority = (Urgency × 30%) + (Strategic × 25%) + 
               (Dependency × 20%) + (Effort × 10%) + 
               (Staleness × 10%) + (Engagement × 5%)
    """
    
    # Calculate all factors
    urgency = calculate_urgency(task)
    strategic = calculate_strategic_value(task)
    dependency = calculate_dependency_score(task, all_tasks)
    effort_impact = calculate_effort_impact(task)
    staleness = calculate_staleness(task)
    engagement = calculate_activity_engagement(task)
    
    # Store breakdown for transparency
    task['priority_breakdown'] = {
        'urgency': round(urgency, 1),
        'strategic_value': round(strategic, 1),
        'dependency_impact': round(dependency, 1),
        'effort_vs_impact': round(effort_impact, 1),
        'staleness': round(staleness, 1),
        'engagement': round(engagement, 1)
    }
    
    # Weighted calculation
    priority_score = (
        (urgency * 0.30) +
        (strategic * 0.25) +
        (dependency * 0.20) +
        (effort_impact * 0.10) +
        (staleness * 0.10) +
        (engagement * 0.05)
    )
    
    return round(min(100, max(0, priority_score)), 1)

# ============================================
# AI ANALYSIS WITH GEMINI
# ============================================

def analyze_task_with_ai(task, all_tasks):
    """Use Gemini to analyze task and provide insights"""
    try:
        priority_breakdown = task.get('priority_breakdown', {})
        
        prompt = f"""
Analyze this project task and provide a brief, actionable insight (3-4 sentences max):

Task: {task['title']}
Description: {task.get('description', 'No description')[:500]}
Status: {task['status']}
Due: {task.get('deadline', 'No deadline')}
Labels: {', '.join(task.get('labels', ['none']))}
Progress: {task.get('completion_pct', 0)}% complete
Priority Score: {task.get('priority_score', 0)}/100
Assignees: {len(task.get('assignee', []))}
Last Activity: {task.get('dateLastActivity', 'Unknown')}

Priority Factors:
- Urgency: {priority_breakdown.get('urgency', 0)}/100
- Strategic: {priority_breakdown.get('strategic_value', 0)}/100
- Dependencies: {priority_breakdown.get('dependency_impact', 0)}/100
- Effort: {priority_breakdown.get('effort_vs_impact', 0)}/100

Provide:
1. Risk assessment (LOW/MEDIUM/HIGH/CRITICAL)
2. Key concern or opportunity
3. One specific, actionable recommendation
4. Estimated time to complete (if possible)

Keep it brief, professional, and actionable.
"""
        response = model.generate_content(prompt, stream=False)
        return response.text
    except Exception as e:
        return f"Analysis unavailable: {str(e)[:100]}"

def predict_project_risk(tasks):
    """Use Gemini to predict if project is at risk"""
    try:
        total = len(tasks)
        if total == 0:
            return "No tasks to analyze"
        
        done_count = sum(1 for t in tasks if t['status'] in ['Done', 'Completed'])
        in_progress = sum(1 for t in tasks if t['status'] == 'In Progress')
        
        overdue = sum(1 for t in tasks if t.get('deadline') and 
                     datetime.fromisoformat(t['deadline'].replace('Z', '+00:00')) < 
                     datetime.now(datetime.now().astimezone().tzinfo))
        
        stale_tasks = sum(1 for t in tasks if t.get('priority_breakdown', {}).get('staleness', 0) > 70)
        
        avg_priority = sum(t.get('priority_score', 0) for t in tasks) / total
        high_priority_count = sum(1 for t in tasks if t.get('priority_score', 0) > 75)
        
        prompt = f"""
Analyze project health and predict risks:

📊 Project Metrics:
- Total Tasks: {total}
- Completed: {done_count} ({round(done_count/total*100)}%)
- In Progress: {in_progress}
- Overdue: {overdue}
- Stale Tasks (>7 days): {stale_tasks}
- Average Priority: {round(avg_priority, 1)}/100
- High Priority Tasks: {high_priority_count}

Recent high-priority tasks: {[t['title'][:40] for t in sorted(tasks, key=lambda x: x.get('priority_score', 0), reverse=True)[:5]]}

Provide (4-5 sentences):
1. Overall Risk Level: LOW/MEDIUM/HIGH/CRITICAL
2. Primary concern or bottleneck
3. Secondary concern (if any)
4. One immediate action to take
5. One strategic recommendation

Be direct, specific, and actionable.
"""
        response = model.generate_content(prompt, stream=False)
        return response.text
    except Exception as e:
        return f"Risk prediction unavailable: {str(e)[:100]}"

def get_ai_recommendations(tasks):
    """Get AI-powered recommendations for task prioritization"""
    try:
        top_10_tasks = sorted(tasks, key=lambda x: x.get('priority_score', 0), reverse=True)[:10]
        
        task_summary = "\n".join([
            f"- [{t['priority_score']}/100] {t['title']} (Status: {t['status']}, Due: {t.get('deadline', 'None')[:10]})"
            for t in top_10_tasks
        ])
        
        prompt = f"""
Review the top 10 priority tasks and provide strategic recommendations:

{task_summary}

Provide:
1. Should priorities be adjusted? (Yes/No and why)
2. Which task should be tackled FIRST today?
3. Any tasks that could be delegated or postponed?
4. Recommended focus areas for this week

Be concise (4-5 sentences total).
"""
        response = model.generate_content(prompt, stream=False)
        return response.text
    except Exception as e:
        return f"Recommendations unavailable: {str(e)[:100]}"

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/', methods=['GET'])
def home():
    """Root endpoint - Health check"""
    return jsonify({
        'status': 'OK',
        'service': 'ProActive Intelligence Hub v2.0',
        'message': 'Enhanced API with improved priority scoring',
        'version': '2.0',
        'features': [
            'Advanced priority scoring algorithm',
            'Dependency tracking',
            'Staleness detection',
            'Effort vs impact analysis',
            'AI-powered insights',
            'Project risk prediction'
        ],
        'endpoints': {
            'health': '/api/health',
            'tasks': '/api/tasks',
            'next_task': '/api/next-task',
            'summary': '/api/summary',
            'analyze': '/api/analyze (POST)',
            'risk': '/api/risk',
            'blockers': '/api/blockers',
            'quick_wins': '/api/quick-wins',
            'stale_tasks': '/api/stale-tasks',
            'recommendations': '/api/recommendations'
        }
    }), 200

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'OK',
        'message': 'ProActive Intelligence Hub v2.0 is running',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0'
    }), 200

@app.route('/api/tasks', methods=['GET'])
def get_all_tasks():
    """Get all tasks with enhanced priority scoring"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        
        if not cards:
            return jsonify({
                'success': False,
                'error': 'No cards found. Check Trello credentials.',
                'cards_count': 0
            }), 200
        
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priority for each task
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Sort by priority
        tasks.sort(key=lambda x: x['priority_score'], reverse=True)
        
        # Calculate statistics
        avg_priority = sum(t['priority_score'] for t in tasks) / len(tasks)
        high_priority = sum(1 for t in tasks if t['priority_score'] > 75)
        medium_priority = sum(1 for t in tasks if 50 <= t['priority_score'] <= 75)
        low_priority = sum(1 for t in tasks if t['priority_score'] < 50)
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/blockers', methods=['GET'])
def get_blockers():
    """Get tasks that are blocking others"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Find blocker tasks
        blockers = []
        for task in tasks:
            labels = [l.lower() for l in task.get('labels', [])]
            desc = task.get('description', '').lower()
            title = task.get('title', '').lower()
            
            if ('blocker' in labels or 'blocker' in desc or 
                'blocking' in title or 'blocks' in desc):
                blockers.append(task)
        
        blockers.sort(key=lambda x: x['priority_score'], reverse=True)
        
        return jsonify({
            'success': True,
            'blockers': blockers,
            'count': len(blockers),
            'message': f"Found {len(blockers)} blocking tasks" if blockers else "No blockers found"
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/quick-wins', methods=['GET'])
def get_quick_wins():
    """Get quick win tasks (low effort, high impact)"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Filter for quick wins (high effort_impact score and not done)
        quick_wins = []
        for task in tasks:
            effort_score = task.get('priority_breakdown', {}).get('effort_vs_impact', 0)
            status = task.get('status', '')
            
            if effort_score > 75 and status not in ['Done', 'Completed']:
                quick_wins.append(task)
        
        quick_wins.sort(key=lambda x: x.get('priority_breakdown', {}).get('effort_vs_impact', 0), reverse=True)
        
        return jsonify({
            'success': True,
            'quick_wins': quick_wins,
            'count': len(quick_wins),
            'message': f"Found {len(quick_wins)} quick win opportunities" if quick_wins else "No quick wins available"
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stale-tasks', methods=['GET'])
def get_stale_tasks():
    """Get stale/stagnant tasks that need attention"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Filter for stale tasks
        stale_tasks = []
        for task in tasks:
            staleness_score = task.get('priority_breakdown', {}).get('staleness', 0)
            status = task.get('status', '')
            
            if staleness_score > 70 and status in ['In Progress', 'In Review', 'Testing']:
                last_activity = task.get('dateLastActivity', '')
                try:
                    last_date = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                    days_stale = (datetime.now(last_date.tzinfo) - last_date).days
                    task['days_stale'] = days_stale
                except:
                    task['days_stale'] = 'Unknown'
                
                stale_tasks.append(task)
        
        stale_tasks.sort(key=lambda x: x.get('priority_breakdown', {}).get('staleness', 0), reverse=True)
        
        return jsonify({
            'success': True,
            'stale_tasks': stale_tasks,
            'count': len(stale_tasks),
            'message': f"⚠️ {len(stale_tasks)} tasks need attention" if stale_tasks else "✅ No stale tasks"
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/recommendations', methods=['GET'])
def get_recommendations():
    """Get AI-powered strategic recommendations"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        if not tasks:
            return jsonify({
                'success': True,
                'message': 'No tasks to analyze'
            }), 200
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        recommendations = get_ai_recommendations(tasks)
        
        return jsonify({
            'success': True,
            'recommendations': recommendations,
            'analyzed_tasks': len(tasks)
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/overdue', methods=['GET'])
def get_overdue_tasks():
    """Get all overdue tasks"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Filter overdue tasks
        now = datetime.now(datetime.now().astimezone().tzinfo)
        overdue_tasks = []
        
        for task in tasks:
            deadline = task.get('deadline')
            if deadline:
                try:
                    deadline_date = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                    if deadline_date < now:
                        days_overdue = (now - deadline_date).days
                        task['days_overdue'] = days_overdue
                        overdue_tasks.append(task)
                except:
                    pass
        
        overdue_tasks.sort(key=lambda x: x.get('days_overdue', 0), reverse=True)
        
        return jsonify({
            'success': True,
            'overdue_tasks': overdue_tasks,
            'count': len(overdue_tasks),
            'message': f"🚨 {len(overdue_tasks)} overdue tasks" if overdue_tasks else "✅ No overdue tasks"
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/priority-breakdown', methods=['GET'])
def get_priority_breakdown():
    """Get detailed breakdown of priority scoring across all tasks"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        if not tasks:
            return jsonify({
                'success': True,
                'message': 'No tasks to analyze'
            }), 200
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Calculate averages for each factor
        total = len(tasks)
        avg_urgency = sum(t.get('priority_breakdown', {}).get('urgency', 0) for t in tasks) / total
        avg_strategic = sum(t.get('priority_breakdown', {}).get('strategic_value', 0) for t in tasks) / total
        avg_dependency = sum(t.get('priority_breakdown', {}).get('dependency_impact', 0) for t in tasks) / total
        avg_effort = sum(t.get('priority_breakdown', {}).get('effort_vs_impact', 0) for t in tasks) / total
        avg_staleness = sum(t.get('priority_breakdown', {}).get('staleness', 0) for t in tasks) / total
        avg_engagement = sum(t.get('priority_breakdown', {}).get('engagement', 0) for t in tasks) / total
        
        return jsonify({
            'success': True,
            'total_tasks': total,
            'average_scores': {
                'urgency': round(avg_urgency, 1),
                'strategic_value': round(avg_strategic, 1),
                'dependency_impact': round(avg_dependency, 1),
                'effort_vs_impact': round(avg_effort, 1),
                'staleness': round(avg_staleness, 1),
                'engagement': round(avg_engagement, 1)
            },
            'weights': {
                'urgency': '30%',
                'strategic_value': '25%',
                'dependency_impact': '20%',
                'effort_vs_impact': '10%',
                'staleness': '10%',
                'engagement': '5%'
            },
            'interpretation': {
                'urgency': 'Based on deadline proximity and overdue status',
                'strategic_value': 'Based on labels, keywords, and business impact',
                'dependency_impact': 'How many tasks this blocks or is blocked by',
                'effort_vs_impact': 'Quick wins score (low effort, high impact)',
                'staleness': 'How long task has been inactive in progress',
                'engagement': 'Comments and activity level'
            }
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/today', methods=['GET'])
def get_today_focus():
    """Get recommended focus tasks for today"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        if not tasks:
            return jsonify({
                'success': True,
                'message': '✅ No tasks for today'
            }), 200
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Filter today's focus: high priority, due soon, or quick wins
        today_tasks = []
        now = datetime.now(datetime.now().astimezone().tzinfo)
        
        for task in tasks:
            status = task.get('status', '')
            if status in ['Done', 'Completed']:
                continue
            
            priority = task.get('priority_score', 0)
            deadline = task.get('deadline')
            effort_score = task.get('priority_breakdown', {}).get('effort_vs_impact', 0)
            
            # Include if: high priority, due today/tomorrow, or quick win
            include = False
            reason = []
            
            if priority > 75:
                include = True
                reason.append('High priority')
            
            if deadline:
                try:
                    deadline_date = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                    hours_until = (deadline_date - now).total_seconds() / 3600
                    if hours_until < 48 and hours_until > 0:
                        include = True
                        reason.append('Due soon')
                except:
                    pass
            
            if effort_score > 80 and priority > 50:
                include = True
                reason.append('Quick win')
            
            if include:
                task['focus_reason'] = ', '.join(reason)
                today_tasks.append(task)
        
        today_tasks.sort(key=lambda x: x['priority_score'], reverse=True)
        today_tasks = today_tasks[:10]  # Limit to top 10
        
        return jsonify({
            'success': True,
            'today_focus': today_tasks,
            'count': len(today_tasks),
            'message': f"🎯 {len(today_tasks)} tasks recommended for today"
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/team-workload', methods=['GET'])
def get_team_workload():
    """Get workload distribution across team members"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Aggregate by assignee
        workload = {}
        unassigned_tasks = []
        
        for task in tasks:
            if task.get('status') in ['Done', 'Completed']:
                continue
            
            assignees = task.get('assignee', [])
            if not assignees:
                unassigned_tasks.append(task)
            else:
                for assignee_id in assignees:
                    if assignee_id not in workload:
                        workload[assignee_id] = {
                            'task_count': 0,
                            'high_priority_count': 0,
                            'total_priority_score': 0,
                            'tasks': []
                        }
                    
                    workload[assignee_id]['task_count'] += 1
                    workload[assignee_id]['total_priority_score'] += task['priority_score']
                    if task['priority_score'] > 75:
                        workload[assignee_id]['high_priority_count'] += 1
                    workload[assignee_id]['tasks'].append({
                        'id': task['id'],
                        'title': task['title'],
                        'priority': task['priority_score'],
                        'status': task['status']
                    })
        
        # Calculate average priority per person
        for assignee_id in workload:
            count = workload[assignee_id]['task_count']
            workload[assignee_id]['avg_priority'] = round(
                workload[assignee_id]['total_priority_score'] / count, 1
            ) if count > 0 else 0
        
        return jsonify({
            'success': True,
            'workload_by_assignee': workload,
            'unassigned_count': len(unassigned_tasks),
            'unassigned_tasks': unassigned_tasks,
            'total_team_members': len(workload)
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Endpoint not found',
        'message': 'The requested endpoint does not exist',
        'available_endpoints': [
            '/api/health',
            '/api/tasks',
            '/api/next-task',
            '/api/summary',
            '/api/analyze',
            '/api/risk',
            '/api/blockers',
            '/api/quick-wins',
            '/api/stale-tasks',
            '/api/recommendations',
            '/api/overdue',
            '/api/priority-breakdown',
            '/api/today',
            '/api/team-workload'
        ]
    }), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({
        'error': 'Server error',
        'message': str(error)
    }), 500

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    # Get port from environment variable (required for Render)
    port = int(os.getenv('PORT', 10000))
    
    print("=" * 60)
    print("🚀 ProActive Intelligence Hub v2.0")
    print("=" * 60)
    print(f"📍 Running on port {port}")
    print(f"🧪 Health check: http://0.0.0.0:{port}/api/health")
    print(f"📚 API docs: http://0.0.0.0:{port}/")
    print("\n✨ New Features:")
    print("   • Enhanced priority scoring (6 factors)")
    print("   • Staleness detection")
    print("   • Quick wins identification")
    print("   • AI-powered recommendations")
    print("   • Team workload tracking")
    print("   • Dependency analysis")
    print("=" * 60)
    
    # CRITICAL: Must bind to 0.0.0.0 for Render
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False  # Disable debug in production
    ) True,
            'total_tasks': len(tasks),
            'statistics': {
                'average_priority': round(avg_priority, 1),
                'high_priority_count': high_priority,
                'medium_priority_count': medium_priority,
                'low_priority_count': low_priority
            },
            'tasks': tasks
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/next-task', methods=['GET'])
def get_next_task():
    """Get the highest priority task with detailed reasoning"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        
        if not cards:
            return jsonify({
                'success': True,
                'message': '✅ No tasks yet!'
            }), 200
        
        tasks = normalize_tasks(cards, lists)
        
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        tasks.sort(key=lambda x: x['priority_score'], reverse=True)
        
        top_task = tasks[0]
        breakdown = top_task.get('priority_breakdown', {})
        
        # Generate reasoning
        reasons = []
        if breakdown.get('urgency', 0) > 70:
            reasons.append(f"⏰ High urgency ({breakdown['urgency']}/100)")
        if breakdown.get('strategic_value', 0) > 70:
            reasons.append(f"⭐ High strategic value ({breakdown['strategic_value']}/100)")
        if breakdown.get('dependency_impact', 0) > 70:
            reasons.append(f"🔗 Blocking other tasks ({breakdown['dependency_impact']}/100)")
        if breakdown.get('staleness', 0) > 70:
            reasons.append(f"⚠️ Stagnant task needs attention ({breakdown['staleness']}/100)")
        
        return jsonify({
            'success': True,
            'task': top_task,
            'message': f"🎯 Top Priority: {top_task['title']}",
            'priority_score': f"{top_task['priority_score']}/100",
            'reasons': reasons,
            'recommendation': 'Focus on this task first to maximize impact'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/summary', methods=['GET'])
def get_summary():
    """Get enhanced project summary with insights"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        
        tasks = normalize_tasks(cards, lists)
        
        if not tasks:
            return jsonify({
                'success': True,
                'message': 'No tasks found'
            }), 200
        
        # Calculate priority scores
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        # Status distribution
        status_counts = {}
        for task in tasks:
            status = task['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Completion rate
        done_count = status_counts.get('Done', 0) + status_counts.get('Completed', 0)
        completion_rate = round((done_count / len(tasks)) * 100) if tasks else 0
        
        # Priority distribution
        high_priority = sum(1 for t in tasks if t['priority_score'] > 75)
        medium_priority = sum(1 for t in tasks if 50 <= t['priority_score'] <= 75)
        low_priority = sum(1 for t in tasks if t['priority_score'] < 50)
        
        # Overdue tasks
        overdue = sum(1 for t in tasks if t.get('deadline') and 
                     datetime.fromisoformat(t['deadline'].replace('Z', '+00:00')) < 
                     datetime.now(datetime.now().astimezone().tzinfo))
        
        # Stale tasks
        stale = sum(1 for t in tasks if t.get('priority_breakdown', {}).get('staleness', 0) > 70)
        
        # Blocked tasks
        blocked = sum(1 for t in tasks if 'blocked' in t.get('description', '').lower() or 
                     'waiting' in t.get('description', '').lower())
        
        return jsonify({
            'success': True,
            'summary': {
                'total_tasks': len(tasks),
                'completion_rate': completion_rate,
                'by_status': status_counts,
                'priority_distribution': {
                    'high': high_priority,
                    'medium': medium_priority,
                    'low': low_priority
                },
                'health_indicators': {
                    'overdue_tasks': overdue,
                    'stale_tasks': stale,
                    'blocked_tasks': blocked
                },
                'average_priority': round(sum(t['priority_score'] for t in tasks) / len(tasks), 1)
            }
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_task_endpoint():
    """Analyze a specific task with AI"""
    try:
        data = request.json
        task_id = data.get('task_id')
        
        if not task_id:
            return jsonify({
                'success': False,
                'error': 'task_id is required'
            }), 400
        
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        task = next((t for t in tasks if t['id'] == task_id), None)
        
        if not task:
            return jsonify({
                'success': False,
                'error': 'Task not found'
            }), 404
        
        analysis = analyze_task_with_ai(task, tasks)
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'task_title': task['title'],
            'priority_score': task['priority_score'],
            'priority_breakdown': task.get('priority_breakdown', {}),
            'analysis': analysis
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/risk', methods=['GET'])
def get_risk_prediction():
    """Get AI risk prediction for project"""
    try:
        cards = get_trello_cards()
        lists = get_trello_lists()
        tasks = normalize_tasks(cards, lists)
        
        if not tasks:
            return jsonify({
                'success': True,
                'message': 'No tasks to analyze'
            }), 200
        
        # Calculate priorities
        for task in tasks:
            task['priority_score'] = calculate_priority_score(task, tasks)
        
        risk_analysis = predict_project_risk(tasks)
        
        return jsonify({
            'success': True,
            'risk_analysis': risk_analysis,
            'task_count': len(tasks)
        }), 200
    except Exception as e:
        return jsonify({
            'success':
