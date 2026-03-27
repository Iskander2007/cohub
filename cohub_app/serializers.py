from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Room, RoomMember, Task, Expense, ExpenseShare, ChatMessage


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class RoomMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = RoomMember
        fields = ['id', 'user', 'user_id', 'room', 'is_admin', 'joined_at']
        read_only_fields = ['joined_at']


class RoomSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    members = RoomMemberSerializer(many=True, read_only=True)
    member_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'code', 'description', 'owner', 'members', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_member_count(self, obj):
        return obj.members.count()


class TaskSerializer(serializers.ModelSerializer):
    assigned_to = UserSerializer(read_only=True)
    assigned_to_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = Task
        fields = ['id', 'room', 'title', 'description', 'assigned_to', 'assigned_to_id', 'status', 
                  'priority', 'due_date', 'created_by', 'created_at', 'updated_at', 'completed_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        assigned_to_id = attrs.get('assigned_to_id')

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})

        if assigned_to_id is not None:
            if not RoomMember.objects.filter(room=room, user_id=assigned_to_id).exists():
                raise serializers.ValidationError({'assigned_to_id': 'Исполнитель должен быть участником комнаты'})

        return attrs


class ExpenseShareSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = ExpenseShare
        fields = ['id', 'expense', 'user', 'amount', 'is_settled']


class ExpenseSerializer(serializers.ModelSerializer):
    paid_by = UserSerializer(read_only=True)
    paid_by_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    shares = ExpenseShareSerializer(many=True, read_only=True)
    
    class Meta:
        model = Expense
        fields = ['id', 'room', 'description', 'amount', 'paid_by', 'paid_by_id', 'date', 
                  'category', 'shares', 'created_at', 'updated_at']
        read_only_fields = ['id', 'shares', 'created_at', 'updated_at']

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        paid_by_id = attrs.get('paid_by_id')

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})

            if paid_by_id is None:
                # If payer is omitted, default to the current user for better UX.
                paid_by_id = request.user.id
                attrs['paid_by_id'] = paid_by_id

        if paid_by_id is not None and not RoomMember.objects.filter(room=room, user_id=paid_by_id).exists():
            raise serializers.ValidationError({'paid_by_id': 'Плательщик должен быть участником комнаты'})

        category = (attrs.get('category') or '').strip()
        attrs['category'] = category or 'прочее'

        if attrs.get('date') is None:
            attrs['date'] = timezone.localdate()

        return attrs


class ChatMessageSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ['id', 'room', 'author', 'author_name', 'text', 'created_at']
        read_only_fields = ['id', 'author', 'author_name', 'created_at']

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        text = (attrs.get('text') or '').strip()

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})

        if not text:
            raise serializers.ValidationError({'text': 'Сообщение не может быть пустым'})

        attrs['text'] = text
        return attrs

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username
